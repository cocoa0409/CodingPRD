"""Loan-level mutation primitives: posture recomputation, version bump, sweep."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from config import (
    BREACH_GRACE_DAYS,
    DEFAULT_GRACE_DAYS,
    MEDIATION_AUTOFAIL_NOI_DAYS,
    MEDIATION_FAILURE_WINDOW_DAYS,
)
from db import store
from services.calculations import past_due_installments
from utils import days_between, floor_days_between, midnight_utc


# ── Helpers ─────────────────────────────────────────────────────────────────


def bump(entity: dict, now: datetime) -> None:
    """Bump updated_at and version on a dict that carries those common fields."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 0) + 1


def loan_has_active_forbearance(loan_id: str) -> bool:
    for fp in store.forbearance_plans.values():
        if fp["loan_id"] == loan_id and fp["status"] == "ACTIVE":
            return True
    return False


def loan_open_foreclosure(loan_id: str):
    for c in store.foreclosure_cases.values():
        if c["loan_id"] == loan_id and c["status"] in (
            "NOI_ISSUED",
            "MEDIATION_OPEN",
            "FILED",
            "AUCTION_SCHEDULED",
        ):
            return c
    return None


def recompute_delinquency_days(loan: dict, now: datetime) -> None:
    """PRD §3.2: 'delinquency_days is recomputed as the integer-day-floor
    of (today minus next_due_date, with zero when the result is negative)'.

    Both 'today' and 'next_due_date' are date-only quantities at UTC
    midnight (PRD §2.4), so this is calendar-day subtraction with the
    negative clamp.
    """
    delta = days_between(now, loan["next_due_date"])
    loan["delinquency_days"] = max(0, delta)


def recompute_posture(loan: dict, now: datetime) -> None:
    """Re-derive Loan.posture from its delinquency + other-entity state.

    Does NOT apply if the loan is in a 'protected' posture
    (FORBEARANCE, FORECLOSURE, REINSTATED, PAID_OFF, DEFAULT) — those
    are driven by explicit transitions, not the delinquency ladder.

    PRD §3.4: 'When the clock advances at least thirty days past
    end_date and cure_balance_cents is still strictly positive, the
    plan transitions to BREACHED and Loan.posture cascades to DEFAULT.'
    DEFAULT must therefore be sticky: a subsequent delinquency_days
    recomputation must not demote a just-breached loan back to
    DELINQUENT. DEFAULT only leaves via the curing payment path
    (recompute_posture is not the right place for that — payment
    handlers explicitly set posture).
    """
    if loan["posture"] in ("FORBEARANCE", "FORECLOSURE", "REINSTATED",
                            "PAID_OFF"):
        return
    # DEFAULT is sticky: a clock advance alone does not move it back to
    # DELINQUENT or CURRENT. Only an actual curing payment (which
    # explicitly recomputes posture after zeroing delinquency_days) can
    # promote DEFAULT → CURRENT. Allow that specific transition here.
    if loan["posture"] == "DEFAULT":
        if loan["delinquency_days"] == 0:
            loan["posture"] = "CURRENT"
        return

    has_active_fp = loan_has_active_forbearance(loan["id"])
    if has_active_fp:
        # Should have been transitioned to FORBEARANCE when the plan was created;
        # idempotent safety net.
        loan["posture"] = "FORBEARANCE"
        return

    dq = loan["delinquency_days"]
    if dq <= 0:
        if loan["posture"] != "CURRENT":
            loan["posture"] = "CURRENT"
        return
    if dq >= DEFAULT_GRACE_DAYS:
        loan["posture"] = "DEFAULT"
        return
    loan["posture"] = "DELINQUENT"


# ── Sweep / time-gated transitions ──────────────────────────────────────────


def run_sweep() -> None:
    """Run every time-gated evaluation in the deterministic order.

    Order (per PRD §2.9 / §3.8):
      1. ForbearancePlan completions/breaches
      2. Loan delinquency_days recomputation + posture re-derivation
      3. Disbursement maturations (PAID or FAILED)
      4. ForeclosureCase auction closings
      5. MediationCase timeouts (OPEN → FAILED after 90 days since noi_sent_at)
    """
    now = store.now()

    # Step 1: Forbearance completions / breaches.
    _sweep_forbearance_plans(now)

    # Step 2: Recompute delinquency + posture.
    for loan in store.loans.values():
        recompute_delinquency_days(loan, now)
        recompute_posture(loan, now)

    # Step 3: Disbursement maturations.
    _sweep_disbursements(now)

    # Step 4: Auction closings.
    _sweep_auctions(now)

    # Step 5: Mediation timeouts.
    _sweep_mediations(now)


def _sweep_forbearance_plans(now: datetime) -> None:
    for fp in list(store.forbearance_plans.values()):
        if fp["status"] != "ACTIVE":
            continue
        loan = store.loans.get(fp["loan_id"])
        if loan is None:
            continue
        end_date = fp["end_date"]
        if midnight_utc(now) < midnight_utc(end_date):
            continue
        # end_date has passed — compute cure_balance and decide.
        _recompute_cure_balance(fp, loan)
        if fp["cure_balance_cents"] <= 0:
            fp["status"] = "COMPLETED"
            bump(fp, now)
            if fp["repayment_method"] == "DEFERRAL":
                loan["principal_balance_cents"] += fp["total_paused_cents"]
            # PRD §3.4: "the plan transitions to COMPLETED and Loan.posture
            # returns to CURRENT". The paused installments are now
            # accounted for (added to principal for DEFERRAL; repaid in
            # cash for cure-method plans that reach cure==0), so resume
            # the schedule. Advance next_due_date past the months that
            # were paused; if the logical clock has already moved beyond
            # that, advance further so the loan starts CURRENT (with
            # dq=0) at the COMPLETED transition.
            from utils import add_months as _add_months
            new_ndd = _add_months(loan["next_due_date"], fp["months"])
            now_m = midnight_utc(now)
            # Keep advancing while next_due_date is in the past so the
            # borrower gets a clean schedule from "this month forward"
            # — consistent with PRD's "returns to CURRENT" semantics.
            while midnight_utc(new_ndd) <= now_m:
                new_ndd = _add_months(new_ndd, 1)
            loan["next_due_date"] = new_ndd
            # Loan returns to CURRENT.
            loan["posture"] = "CURRENT"
            loan["delinquency_days"] = 0
            bump(loan, now)
        else:
            # Breach only after 30 days past end_date.
            days_past = floor_days_between(midnight_utc(now), midnight_utc(end_date))
            if days_past >= BREACH_GRACE_DAYS:
                fp["status"] = "BREACHED"
                bump(fp, now)
                loan["posture"] = "DEFAULT"
                bump(loan, now)


def _recompute_cure_balance(fp: dict, loan: dict) -> None:
    """fp.cure_balance_cents = total_paused - sum(post-end payments applied to cure).

    PRD §3.4: "Under DEFERRAL, cure_balance_cents is immediately zero
    upon the COMPLETED transition and total_paused_cents is added to
    principal_balance_cents (deferred to maturity, with no interest
    accrual on the deferred amount)." Thus the DEFERRAL repayment
    method short-circuits cure_balance to zero — the deferred amount
    is repaid via the principal-balance addition rather than via
    cash payments during the cure window.
    """
    if fp["repayment_method"] == "DEFERRAL":
        fp["cure_balance_cents"] = 0
        return
    cure = fp["total_paused_cents"]
    payments = [
        p
        for p in store.payments.values()
        if p["loan_id"] == loan["id"]
        and p["status"] == "POSTED"
        and midnight_utc(p["received_date"]) >= midnight_utc(fp["end_date"])
    ]
    # Sort by received_date then created_at.
    payments.sort(key=lambda p: (midnight_utc(p["received_date"]), p["created_at"]))
    for p in payments:
        applied = min(
            cure,
            p["allocation_principal_cents"] + p["allocation_interest_cents"] + p["allocation_escrow_cents"],
        )
        cure -= applied
        if cure <= 0:
            cure = 0
            break
    fp["cure_balance_cents"] = max(0, cure)


def _sweep_disbursements(now: datetime) -> None:
    for d in list(store.disbursements.values()):
        if d["status"] != "SCHEDULED":
            continue
        if midnight_utc(now) < midnight_utc(d["scheduled_date"]):
            continue
        loan = store.loans.get(d["loan_id"])
        if loan is None:
            continue
        if loan["posture"] == "PAID_OFF":
            # Tax/insurance auto-cancelled at PAID_OFF; surplus refunds remain.
            if d["type"] in ("PROPERTY_TAX", "HAZARD_INSURANCE"):
                d["status"] = "CANCELED"
                bump(d, now)
            continue
        if loan["escrow_balance_cents"] >= d["amount_cents"]:
            d["status"] = "PAID"
            d["paid_at"] = now
            d["failure_reason"] = None
            loan["escrow_balance_cents"] -= d["amount_cents"]
            bump(d, now)
            bump(loan, now)
        else:
            d["status"] = "FAILED"
            d["failure_reason"] = "INSUFFICIENT_ESCROW"
            bump(d, now)


def _sweep_auctions(now: datetime) -> None:
    for c in list(store.foreclosure_cases.values()):
        if c["status"] != "AUCTION_SCHEDULED":
            continue
        if midnight_utc(now) >= midnight_utc(c["auction_date"]):
            c["status"] = "CLOSED_SOLD"
            bump(c, now)


def _sweep_mediations(now: datetime) -> None:
    for m in list(store.mediation_cases.values()):
        if m["status"] != "OPEN":
            continue
        case = store.foreclosure_cases.get(m["foreclosure_case_id"])
        if case is None or case.get("noi_sent_at") is None:
            continue
        days_since_noi = floor_days_between(midnight_utc(now), midnight_utc(case["noi_sent_at"]))
        if days_since_noi >= MEDIATION_FAILURE_WINDOW_DAYS:
            m["status"] = "FAILED"
            bump(m, now)


# ── Posture transition helpers used by routes ───────────────────────────────


def maybe_become_paid_off(loan: dict, now: datetime) -> None:
    if (
        loan["posture"] == "CURRENT"
        and loan["principal_balance_cents"] == 0
        and loan["escrow_balance_cents"] >= 0
    ):
        loan["posture"] = "PAID_OFF"
        # Cancel SCHEDULED PROPERTY_TAX / HAZARD_INSURANCE disbursements.
        for d in list(store.disbursements.values()):
            if d["loan_id"] != loan["id"]:
                continue
            if d["status"] == "SCHEDULED" and d["type"] in ("PROPERTY_TAX", "HAZARD_INSURANCE"):
                d["status"] = "CANCELED"
                bump(d, now)
