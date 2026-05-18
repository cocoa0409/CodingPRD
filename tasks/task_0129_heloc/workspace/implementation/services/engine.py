"""HELOC lifecycle engine: state transitions, calculations, cascades, sweeps.

All money values are integer cents.  All rate values are integer basis
points.  Intermediate computation uses Decimal so the documented
round-half-up at the end is faithful (PRD §2.6).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, getcontext
from typing import Optional

from config import (
    ANNIVERSARY_DAYS,
    DAYS_PER_CYCLE,
    DAYS_PER_YEAR_ACCRUAL,
    DEFAULT_TRIGGER_PRIORITY,
    DELINQUENCY_DEFAULT_THRESHOLD_DAYS,
    DRAW_PERIOD_DAYS,
    EARLY_CLOSURE_WINDOW_DAYS,
)
from db import store
from utils import (
    ceil_div,
    new_uuid,
    round_half_up,
    whole_days_between,
)

# 60 digits of precision keeps the amortisation formula faithful for
# any (principal, rate, n) combination in our domain.
getcontext().prec = 60


# ────────────────────────────────────────────────────────────────────────────
# Calculation: minimum_payment_due_cents (scaffold §1.3, PRD §3.4)
# ────────────────────────────────────────────────────────────────────────────


def minimum_payment_due_cents(heloc: dict) -> int:
    status = heloc["status"]
    if status == "DRAW":
        # Interest-only minimum.
        return int(heloc["accrued_interest_cents"])
    if status == "REPAY":
        now = store.logical_now()
        end = heloc["repayment_period_end_date"].replace(microsecond=0)
        days_remaining = (end - now).total_seconds() / 86400.0
        if days_remaining <= 0:
            return int(heloc["principal_balance_cents"] + heloc["accrued_interest_cents"])
        months_remaining = ceil_div(int((end - now).total_seconds()), 86400 * 30)
        # Guard: ceiling of a positive value is always >= 1, but be safe.
        if months_remaining <= 0:
            return int(heloc["principal_balance_cents"] + heloc["accrued_interest_cents"])
        rate_bps = heloc["current_rate_bps"]
        principal = heloc["principal_balance_cents"]
        if rate_bps == 0:
            # Even split of principal over the remaining cycle count.
            monthly_pi = Decimal(principal) / Decimal(months_remaining)
        else:
            monthly_rate = Decimal(rate_bps) / Decimal(10000) / Decimal(12)
            # mortgage formula: P * r / (1 - (1+r)^-n)
            one_plus_r_pow = (Decimal(1) + monthly_rate) ** (-months_remaining)
            denom = Decimal(1) - one_plus_r_pow
            monthly_pi = Decimal(principal) * monthly_rate / denom
        total = monthly_pi + Decimal(heloc["accrued_interest_cents"])
        return round_half_up(total)
    if status == "DEFAULT":
        return int(heloc["principal_balance_cents"] + heloc["accrued_interest_cents"])
    # PENDING or CLOSED.
    return 0


# ────────────────────────────────────────────────────────────────────────────
# Calculation: applied_rate_bps (scaffold §1.3, PRD §3.5)
# ────────────────────────────────────────────────────────────────────────────


def compute_applied_rate_bps(
    *,
    prime_rate_bps: int,
    margin_bps: int,
    current_rate_bps: int,
    periodic_cap_bps: int,
    lifetime_floor_bps: int,
    lifetime_cap_bps: int,
) -> tuple[int, int]:
    """Return (requested_rate_bps, applied_rate_bps).

    Two successive clamps:
      1. Periodic cap against CURRENT rate (NOT initial).
      2. Lifetime [floor, cap] bounds (absolute across all resets).
    """
    requested = prime_rate_bps + margin_bps
    delta = requested - current_rate_bps
    if delta > periodic_cap_bps:
        periodic_clamped = current_rate_bps + periodic_cap_bps
    elif delta < -periodic_cap_bps:
        periodic_clamped = current_rate_bps - periodic_cap_bps
    else:
        periodic_clamped = requested
    applied = max(lifetime_floor_bps, min(lifetime_cap_bps, periodic_clamped))
    return requested, applied


# ────────────────────────────────────────────────────────────────────────────
# Calculation: payment waterfall (scaffold §1.3, PRD §3.4)
# ────────────────────────────────────────────────────────────────────────────


def apply_payment_waterfall(heloc: dict, amount_cents: int) -> tuple[int, int]:
    """Interest-first, then principal. Both are integer-cent waterfalls.

    Returns (interest_component_cents, principal_component_cents).
    Caller is responsible for persisting the Payment record + bumping
    heloc.updated_at and heloc.version.
    """
    interest_component = min(amount_cents, heloc["accrued_interest_cents"])
    principal_component = amount_cents - interest_component
    heloc["accrued_interest_cents"] -= interest_component
    # Principal floor at zero per PRD §3.4 — never goes negative.
    new_principal = heloc["principal_balance_cents"] - principal_component
    if new_principal < 0:
        new_principal = 0
    heloc["principal_balance_cents"] = new_principal
    # Available credit grows back as principal is paid down, but the
    # PRD only specifies available_credit_cents as a function of
    # credit_limit - principal_balance, so recompute it for callers
    # who use the stored value (it's the same as that derivation).
    heloc["available_credit_cents"] = heloc["credit_limit_cents"] - heloc["principal_balance_cents"]
    return interest_component, principal_component


# ────────────────────────────────────────────────────────────────────────────
# Common-field bookkeeping (scaffold §1.1 "common_fields: true")
# ────────────────────────────────────────────────────────────────────────────


def stamp_create(entity: dict) -> None:
    """Stamp a freshly-created common-fields entity with id/created_at/version."""
    now = store.now()
    entity["id"] = new_uuid()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1


def stamp_update(entity: dict) -> None:
    """Refresh updated_at and bump version on a common-fields entity."""
    entity["updated_at"] = store.now()
    entity["version"] = int(entity.get("version", 1)) + 1


def stamp_ledger(entity: dict) -> None:
    """Stamp an immutable ledger/audit entity with id + created_at only."""
    entity["id"] = new_uuid()
    entity["created_at"] = store.now()


# ────────────────────────────────────────────────────────────────────────────
# Default-trigger priority resolution (PRD §2.9)
# ────────────────────────────────────────────────────────────────────────────


def _trigger_priority(trigger: str) -> int:
    return DEFAULT_TRIGGER_PRIORITY.get(trigger, 0)


def maybe_default_heloc(
    heloc: dict,
    *,
    trigger: str,
    source_event_id: Optional[str],
) -> Optional[dict]:
    """Transition a HELOC to DEFAULT if it is currently in {DRAW, REPAY}.

    Implements the priority rule (PRD §2.9): if the HELOC is already
    in DEFAULT (or simultaneously matches multiple triggers), the
    stored default_trigger reflects the highest-priority trigger.

    Returns the created DefaultEvent dict (which the caller MAY want
    to use as a source_event_id) or None when the HELOC was already
    in DEFAULT and the new trigger has lower priority.
    """
    status = heloc["status"]
    if status not in ("DRAW", "REPAY"):
        # Already in DEFAULT / CLOSED — possibly refresh the recorded
        # trigger to the higher-priority one if applicable.
        if status == "DEFAULT":
            current_trigger = heloc.get("default_trigger")
            if _trigger_priority(trigger) > _trigger_priority(current_trigger or ""):
                heloc["default_trigger"] = trigger
                stamp_update(heloc)
                # Always emit a DefaultEvent for the audit log of the
                # cascade hop, mirroring the §2.8 "each cascaded
                # default is a mutation on that HELOC" wording.
                evt = {
                    "heloc_id": heloc["id"],
                    "trigger": trigger,
                    "source_event_id": source_event_id,
                    "recorded_at": store.now(),
                }
                stamp_ledger(evt)
                store.default_events[evt["id"]] = evt
                return evt
        return None

    # First transition into DEFAULT for this HELOC.
    heloc["status"] = "DEFAULT"
    heloc["default_trigger"] = trigger
    heloc["defaulted_at"] = store.now()
    stamp_update(heloc)

    evt = {
        "heloc_id": heloc["id"],
        "trigger": trigger,
        "source_event_id": source_event_id,
        "recorded_at": store.now(),
    }
    stamp_ledger(evt)
    store.default_events[evt["id"]] = evt
    return evt


def cascade_default_for_borrower(borrower_id: str, source_event_id: str) -> int:
    """Cascade BANKRUPTCY to every DRAW/REPAY HELOC owned by this borrower."""
    count = 0
    # Deterministic order — sort by HELOC id.
    for heloc in sorted(store.helocs.values(), key=lambda h: h["id"]):
        if heloc["borrower_id"] != borrower_id:
            continue
        if maybe_default_heloc(heloc, trigger="BANKRUPTCY", source_event_id=source_event_id):
            count += 1
    return count


def cascade_default_for_property(property_id: str, source_event_id: str, *, trigger: str) -> int:
    """Cascade INSURANCE_LAPSE or SENIOR_LIEN_DEFAULT to HELOCs on this property."""
    count = 0
    for heloc in sorted(store.helocs.values(), key=lambda h: h["id"]):
        if heloc["property_id"] != property_id:
            continue
        if maybe_default_heloc(heloc, trigger=trigger, source_event_id=source_event_id):
            count += 1
    return count


# ────────────────────────────────────────────────────────────────────────────
# Early-closure fee evaluation (scaffold §1.3, PRD §3.9)
# ────────────────────────────────────────────────────────────────────────────


def maybe_assess_early_closure_fee(heloc: dict) -> Optional[dict]:
    """Create an EARLY_CLOSURE Fee iff tenure < 1095 days and fee > 0.

    PRD §3.9: "The tenure of the account is the whole-day difference
    between closed_at and origination_date."  Both values come from the
    logical server clock (PRD §2.11) — the implementation adds a
    microsecond tick to disambiguate same-second writes (ordering only).
    We strip microseconds before differencing so the tenure reflects the
    LOGICAL day count, not the per-write tick offset.
    """
    closed_at_logical = heloc["closed_at"].replace(microsecond=0)
    origination_logical = heloc["origination_date"].replace(microsecond=0)
    tenure_days = whole_days_between(closed_at_logical, origination_logical)
    if tenure_days < EARLY_CLOSURE_WINDOW_DAYS and heloc["early_closure_fee_cents"] > 0:
        fee = {
            "heloc_id": heloc["id"],
            "fee_type": "EARLY_CLOSURE",
            "amount_cents": heloc["early_closure_fee_cents"],
            "status": "ASSESSED",
            "assessed_at": store.now(),
        }
        stamp_ledger(fee)
        store.fees[fee["id"]] = fee
        return fee
    return None


# ────────────────────────────────────────────────────────────────────────────
# Sweep: billing cycle (scaffold §1.3, PRD §3.7)
# ────────────────────────────────────────────────────────────────────────────


def _accrue_cycle_interest(heloc: dict) -> int:
    """Return the cycle's interest accrual in cents (round-half-up)."""
    principal = Decimal(heloc["principal_balance_cents"])
    rate = Decimal(heloc["current_rate_bps"]) / Decimal(10000)
    days = Decimal(DAYS_PER_CYCLE)
    year = Decimal(DAYS_PER_YEAR_ACCRUAL)
    interest = principal * rate * days / year
    return round_half_up(interest)


def run_billing_cycle_sweep() -> dict:
    """Advance every HELOC in {DRAW, REPAY} by exactly one 30-day cycle.

    Idempotent per (heloc_id, cycle_index): each invocation processes
    at most one cycle per HELOC.  This matches the scaffold's
    "advances every active Heloc by ONE 30-day cycle" semantics.
    """
    cycles_run = 0
    defaults_triggered = 0
    # Use logical_now (tick-free) for time-threshold comparisons so the
    # DRAW->REPAY rollover fires exactly when the logical clock has
    # reached draw_period_end_date, independent of microsecond ordering.
    now = store.logical_now()

    # Deterministic order by HELOC id (scaffold input_set guidance).
    for heloc in sorted(store.helocs.values(), key=lambda h: h["id"]):
        if heloc["status"] not in ("DRAW", "REPAY"):
            continue

        last_end = heloc["last_cycle_end_date"]
        # PRD §3.7: "The sweep is idempotent per (heloc_id, cycle_index)
        # pair, so re-running the sweep without advancing the clock does
        # not double-accrue interest or double-increment delinquency."
        # Only process this HELOC's next cycle if the logical clock has
        # actually reached the cycle's end.
        next_cycle_end = last_end + timedelta(days=DAYS_PER_CYCLE)
        # Compare at second granularity to avoid microsecond drift.
        if now.replace(microsecond=0) < next_cycle_end.replace(microsecond=0):
            continue

        # We process exactly one cycle per invocation per HELOC.
        # Step 1: accrue interest.
        cycle_interest = _accrue_cycle_interest(heloc)
        heloc["accrued_interest_cents"] += cycle_interest

        # Step 2: snapshot prior cycle's minimum payment for the
        # delinquency check (the cycle's minimum is what the borrower
        # was expected to pay during the just-ended cycle).
        # We compute the minimum AGAINST THE PRE-ACCRUAL STATE for the
        # cycle that is ending: re-derive by subtracting back the accrual.
        prior_state = dict(heloc)
        prior_state["accrued_interest_cents"] = heloc["accrued_interest_cents"] - cycle_interest
        prior_minimum = minimum_payment_due_cents(prior_state)

        # Step 3: payments inside this cycle window.
        cycle_start = last_end
        cycle_end = last_end + timedelta(days=DAYS_PER_CYCLE)
        paid_in_cycle = sum(
            p["amount_cents"]
            for p in store.payments.values()
            if p["heloc_id"] == heloc["id"]
            and cycle_start < p["posted_at"] <= cycle_end
        )

        # Step 4: delinquency update.
        if paid_in_cycle >= prior_minimum:
            heloc["delinquency_days"] = 0
        else:
            heloc["delinquency_days"] += DAYS_PER_CYCLE

        # Step 5: advance last_cycle_end_date.
        heloc["last_cycle_end_date"] = cycle_end
        stamp_update(heloc)

        cycles_run += 1

        # AFTER the cycle, check default trigger (DELINQUENCY_90).
        if (
            heloc["delinquency_days"] >= DELINQUENCY_DEFAULT_THRESHOLD_DAYS
            and heloc["status"] in ("DRAW", "REPAY")
        ):
            if maybe_default_heloc(
                heloc, trigger="DELINQUENCY_90", source_event_id=None
            ):
                defaults_triggered += 1

        # Period rollover DRAW -> REPAY (only if not just defaulted).
        # Compare at second granularity (drop microsecond tick) so an
        # exact 3650-day advance triggers the rollover.
        draw_end = heloc["draw_period_end_date"].replace(microsecond=0)
        if heloc["status"] == "DRAW" and now >= draw_end:
            heloc["status"] = "REPAY"
            stamp_update(heloc)

    return {"cycles_run": cycles_run, "defaults_triggered": defaults_triggered}


# ────────────────────────────────────────────────────────────────────────────
# Sweep: annual fees (scaffold §1.3, PRD §3.8)
# ────────────────────────────────────────────────────────────────────────────


def run_annual_fee_sweep() -> dict:
    """Assess any due ANNUAL fees on all eligible HELOCs.

    Idempotent per (heloc_id, anniversary_index): tracked via
    store.annual_fee_sweep_index[heloc_id] = the highest n already
    assessed (or recorded as WAIVED).  Suppressed when HELOC is in
    {DEFAULT, CLOSED}.
    """
    # logical_now (tick-free) so an exact 365-day advance triggers
    # the first anniversary even if origination_date used a later
    # microsecond tick than the post-advance clock.
    now = store.logical_now()
    fees_created = 0
    for heloc in sorted(store.helocs.values(), key=lambda h: h["id"]):
        origination = heloc.get("origination_date")
        if origination is None:
            # PENDING — never originated, no anniversaries.
            continue
        # Strip the microsecond tick from origination_date so anniversary
        # arithmetic operates at second granularity (the only granularity
        # the test-driving clock can be advanced at).
        origination = origination.replace(microsecond=0)
        last_n = store.annual_fee_sweep_index.get(heloc["id"], 0)
        # Walk forward through eligible anniversaries.
        while True:
            n = last_n + 1
            anniv = origination + timedelta(days=ANNIVERSARY_DAYS * n)
            if now < anniv:
                break
            # Suppress on DEFAULT / CLOSED — but still advance the
            # index so we never reassess this anniversary even if the
            # HELOC later transitions out of DEFAULT (it can't here,
            # but the idempotency invariant is per-anniversary regardless).
            if heloc["status"] in ("DEFAULT", "CLOSED"):
                last_n = n
                store.annual_fee_sweep_index[heloc["id"]] = last_n
                continue
            # Eligible assessment.
            if n == 1 and heloc["annual_fee_waived_first_year"]:
                fee = {
                    "heloc_id": heloc["id"],
                    "fee_type": "ANNUAL",
                    "amount_cents": 0,
                    "status": "WAIVED",
                    "assessed_at": store.now(),
                }
            else:
                fee = {
                    "heloc_id": heloc["id"],
                    "fee_type": "ANNUAL",
                    "amount_cents": heloc["annual_fee_cents"],
                    "status": "ASSESSED",
                    "assessed_at": store.now(),
                }
            stamp_ledger(fee)
            store.fees[fee["id"]] = fee
            fees_created += 1
            last_n = n
            store.annual_fee_sweep_index[heloc["id"]] = last_n
    return {"fees_created": fees_created}
