"""Payment allocation waterfall (§3.4) and PSLF qualification check (§3.8)."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from ..clock import (
    days_between,
    first_of_month_at_or_after,
    format_iso,
    now_dt,
    now_iso_ms,
    parse_iso,
)
from ..money import D, round_half_up_to_int
from ..store import bump_version, get_store
from . import loans as loan_svc
from .borrowers import non_terminal_loans, recompute_aggregates


TARGETED_SOURCES = {"ADMINISTRATIVE_WAGE_GARNISHMENT", "TREASURY_OFFSET"}


def _priority_key(loan: dict[str, Any]):
    """Sort priority: interest_rate_bps DESC, disbursement_date ASC, id ASC."""
    return (-int(loan["interest_rate_bps"]), loan.get("disbursement_date", ""), loan["id"])


def allocate_payment(
    borrower: dict[str, Any],
    amount_cents: int,
    source: str,
    received_at_iso: str,
) -> list[dict[str, Any]]:
    """Run the waterfall. Returns the allocations array.

    Mutates loan balances and statuses (PAID_OFF on zero). Caller is
    responsible for bumping borrower aggregates and storing the Payment.
    """
    bid = borrower["id"]
    loans = non_terminal_loans(bid)
    loans.sort(key=_priority_key)

    targeted = source in TARGETED_SOURCES
    if targeted:
        eligible = [l for l in loans if l["status"] == "DEFAULT"]
    else:
        eligible = loans

    remaining = int(amount_cents)
    allocations: list[dict[str, Any]] = []
    # We track every eligible loan in iteration order so that we can refund
    # excess to the highest-priority one.
    for loan in eligible:
        if remaining <= 0:
            break
        interest_part = 0
        principal_part = 0
        # accrued interest first
        accrued = int(loan["accrued_interest_cents"])
        if accrued > 0:
            take = min(remaining, accrued)
            loan["accrued_interest_cents"] = accrued - take
            interest_part = take
            remaining -= take
        if remaining > 0:
            principal = int(loan["principal_balance_cents"])
            if principal > 0:
                take = min(remaining, principal)
                loan["principal_balance_cents"] = principal - take
                principal_part = take
                remaining -= take
        if interest_part > 0 or principal_part > 0:
            allocations.append(
                {
                    "loan_id": loan["id"],
                    "fees_cents": 0,
                    "interest_cents": interest_part,
                    "principal_cents": principal_part,
                }
            )

    # Post-allocation transitions
    rcv_dt = parse_iso(received_at_iso)
    for loan in eligible:
        if (
            int(loan["principal_balance_cents"]) == 0
            and int(loan["accrued_interest_cents"]) == 0
            and loan["status"] not in ("PAID_OFF", "DISCHARGED")
        ):
            loan_svc.set_status(loan, "PAID_OFF")
        elif loan["status"] == "DELINQUENT" and not targeted:
            # If the cumulative payment cures past-due installments, return to REPAYMENT.
            # We treat any payment that covers at least one full monthly installment as
            # curing one month; advance last_payment_due_at by that many months.
            plan_monthly = _scheduled_monthly_for_loan(borrower, loan)
            paid_to_loan = 0
            for a in allocations:
                if a["loan_id"] == loan["id"]:
                    paid_to_loan = a["interest_cents"] + a["principal_cents"]
                    break
            if plan_monthly > 0 and paid_to_loan >= plan_monthly:
                # Advance by N months covered.
                n_months = paid_to_loan // plan_monthly
                loan["days_past_due"] = 0
                # advance last_payment_due_at by n_months
                if loan.get("last_payment_due_at"):
                    base = parse_iso(loan["last_payment_due_at"])
                    new_due = _add_months(base, n_months)
                    loan["last_payment_due_at"] = format_iso(new_due)
                loan_svc.set_status(loan, "REPAYMENT")

    # Refund residual back as a refund_cents bucket on highest-priority allocation.
    if remaining > 0 and allocations:
        allocations[0]["refund_cents"] = int(remaining)
    elif remaining > 0:
        # No allocations happened (eg. targeted-mode but no DEFAULT loans). Put
        # the refund as a synthetic allocation referencing the highest-priority
        # loan if any exist.
        if eligible:
            allocations.append(
                {
                    "loan_id": eligible[0]["id"],
                    "fees_cents": 0,
                    "interest_cents": 0,
                    "principal_cents": 0,
                    "refund_cents": int(remaining),
                }
            )

    # Update borrower aggregates
    recompute_aggregates(borrower)
    return allocations


def _add_months(dt, months: int):
    """Approximate month addition by 30 days each (good enough for installment due dates)."""
    from datetime import timedelta
    return dt + timedelta(days=30 * months)


def _scheduled_monthly_for_loan(
    borrower: dict[str, Any], loan: dict[str, Any]
) -> int:
    """Per-loan scheduled monthly share = round_half_up(plan.monthly_payment_cents * loan_pool_share).

    Returns 0 if no ACTIVE plan covers this loan.
    """
    plan = _active_plan_covering(borrower["id"], loan["id"])
    if not plan:
        return 0
    pool_loans = [
        get_store().loans[lid]
        for lid in plan.get("included_loan_ids", [])
        if lid in get_store().loans
        and get_store().loans[lid]["status"] in ("REPAYMENT", "GRACE", "DELINQUENT", "FORBEARANCE", "DEFERMENT")
    ]
    pool_total = sum(
        int(l["principal_balance_cents"]) + int(l["accrued_interest_cents"])
        for l in pool_loans
    )
    if pool_total <= 0:
        return int(plan.get("monthly_payment_cents", 0))
    this_pool = int(loan["principal_balance_cents"]) + int(loan["accrued_interest_cents"])
    share = D(int(plan.get("monthly_payment_cents", 0))) * D(this_pool) / D(pool_total)
    return round_half_up_to_int(share)


def _active_plan_covering(borrower_id: str, loan_id: str) -> Optional[dict[str, Any]]:
    for plan in get_store().plans.values():
        if (
            plan.get("borrower_id") == borrower_id
            and plan.get("status") == "ACTIVE"
            and loan_id in plan.get("included_loan_ids", [])
        ):
            return plan
    return None


# ---------------------------------------------------------------------------
# PSLF qualification check (§3.8)
# ---------------------------------------------------------------------------
def recount_pslf_for_borrower(borrower_id: str) -> None:
    """Replay the borrower's payment history and recompute qualifying_pslf_payment_count
    per loan, by checking the five PSLF eligibility conditions."""
    store = get_store()
    loans = [l for l in store.loans.values() if l.get("borrower_id") == borrower_id]
    for l in loans:
        l["qualifying_pslf_payment_count"] = 0
    # gather approved certs
    approved_certs = [
        c
        for c in store.employment_certifications.values()
        if c.get("borrower_id") == borrower_id and c.get("status") == "APPROVED"
    ]
    payments = [p for p in store.payments.values() if p.get("borrower_id") == borrower_id]
    payments.sort(key=lambda p: (p.get("received_at", ""), p.get("created_at", "")))
    for p in payments:
        try:
            received_dt = parse_iso(p["received_at"])
        except Exception:
            continue
        covered = False
        for c in approved_certs:
            try:
                ps = parse_iso(c["period_start"])
                pe = parse_iso(c["period_end"])
            except Exception:
                continue
            if ps <= received_dt <= pe:
                covered = True
                break
        if not covered:
            continue
        # Now check each allocation
        for a in p.get("allocations", []):
            loan = store.loans.get(a["loan_id"])
            if not loan:
                continue
            if loan["loan_type"] not in (
                "DIRECT_SUBSIDIZED",
                "DIRECT_UNSUBSIDIZED",
                "DIRECT_PLUS",
            ):
                continue
            # condition 3 & 4: active plan covering loan with sufficient share
            plan_at_time = _plan_active_at_covering(
                borrower_id, loan["id"], received_dt
            )
            if not plan_at_time:
                continue
            if plan_at_time["plan_type"] not in ("STANDARD_10", "IBR", "PAYE", "SAVE"):
                continue
            share = _historical_scheduled_share(plan_at_time, loan)
            paid = int(a.get("interest_cents", 0)) + int(a.get("principal_cents", 0))
            if paid < share:
                continue
            # condition 5: loan not in DEFAULT/DELINQUENT at received_at
            if loan["status"] in ("DEFAULT", "DELINQUENT"):
                continue
            loan["qualifying_pslf_payment_count"] = (
                int(loan.get("qualifying_pslf_payment_count", 0)) + 1
            )


def _plan_active_at_covering(borrower_id: str, loan_id: str, instant) -> Optional[dict[str, Any]]:
    """Find an ACTIVE/SUPERSEDED plan covering loan at instant. We look at plans whose
    effective_from <= instant and which cover this loan; SUPERSEDED plans were
    once ACTIVE at the relevant moment, so they qualify retroactively."""
    candidates: list[dict[str, Any]] = []
    for plan in get_store().plans.values():
        if plan.get("borrower_id") != borrower_id:
            continue
        if loan_id not in plan.get("included_loan_ids", []):
            continue
        if plan.get("status") in ("PENDING", "TERMINATED"):
            continue
        ef = plan.get("effective_from")
        if not ef:
            continue
        try:
            ef_dt = parse_iso(ef)
        except Exception:
            continue
        if ef_dt > instant:
            continue
        candidates.append(plan)
    if not candidates:
        return None
    # pick the latest plan whose effective_from <= instant.
    candidates.sort(key=lambda p: parse_iso(p["effective_from"]), reverse=True)
    return candidates[0]


def _historical_scheduled_share(plan: dict[str, Any], loan: dict[str, Any]) -> int:
    """Historical share for PSLF count - use current pool snapshot since we
    don't keep history. This approximates the scheduled-monthly-share."""
    bid = plan["borrower_id"]
    pool_loans = [
        get_store().loans[lid]
        for lid in plan.get("included_loan_ids", [])
        if lid in get_store().loans
    ]
    pool_total = sum(
        int(l["principal_balance_cents"]) + int(l["accrued_interest_cents"])
        for l in pool_loans
    )
    if pool_total <= 0:
        return int(plan.get("monthly_payment_cents", 0))
    this_pool = int(loan["principal_balance_cents"]) + int(loan["accrued_interest_cents"])
    share = D(int(plan.get("monthly_payment_cents", 0))) * D(this_pool) / D(pool_total)
    return round_half_up_to_int(share)


def is_pslf_qualifying_for_payment(
    borrower_id: str, payment: dict[str, Any]
) -> bool:
    """Whether ANY allocation in this payment qualifies for PSLF (used to set
    pslf_qualifying boolean on the new payment)."""
    try:
        received_dt = parse_iso(payment["received_at"])
    except Exception:
        return False
    store = get_store()
    approved_certs = [
        c
        for c in store.employment_certifications.values()
        if c.get("borrower_id") == borrower_id and c.get("status") == "APPROVED"
    ]
    covered = False
    for c in approved_certs:
        try:
            ps = parse_iso(c["period_start"])
            pe = parse_iso(c["period_end"])
        except Exception:
            continue
        if ps <= received_dt <= pe:
            covered = True
            break
    if not covered:
        return False
    for a in payment.get("allocations", []):
        loan = store.loans.get(a["loan_id"])
        if not loan or loan["loan_type"] not in (
            "DIRECT_SUBSIDIZED",
            "DIRECT_UNSUBSIDIZED",
            "DIRECT_PLUS",
        ):
            continue
        plan_at_time = _plan_active_at_covering(borrower_id, loan["id"], received_dt)
        if not plan_at_time:
            continue
        if plan_at_time["plan_type"] not in ("STANDARD_10", "IBR", "PAYE", "SAVE"):
            continue
        share = _historical_scheduled_share(plan_at_time, loan)
        paid = int(a.get("interest_cents", 0)) + int(a.get("principal_cents", 0))
        if paid < share:
            continue
        if loan["status"] in ("DEFAULT", "DELINQUENT"):
            continue
        return True
    return False
