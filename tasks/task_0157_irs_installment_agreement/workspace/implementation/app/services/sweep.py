"""Sweep + clock-advance helpers.

Implements:
  - Monthly accrual on liabilities with status OPEN, IN_AGREEMENT, CNC
  - Missed-payment detection on ACTIVE installment agreements
  - CSED expiration: liability status OPEN/CNC + now >= csed_effective_date → EXPIRED
  - CNC review-due expiration
"""
from __future__ import annotations

from datetime import timedelta
from typing import List

from app.services.calculations import interest_for_cycle, penalty_for_cycle
from app.services.common import bump_version
from app.services.csed import close_events_of_kind, open_event, recompute_csed
from app.services.liabilities import recompute_balance, set_status
from app.services.liens import release_check
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE
from app.timeutil import (
    CLOCK,
    add_months,
    add_one_month,
    end_of_month,
    fmt,
    now_iso,
    parse_iso,
)


# ---------------------------------------------------------------------------
# Monthly accrual
# ---------------------------------------------------------------------------

def _accrue_liability(liab: dict, current_eom_dt) -> bool:
    """Apply all pending end-of-month accrual cycles up through `current_eom_dt`.

    Returns True if any cycle was applied.
    """
    if liab["status"] not in ("OPEN", "IN_AGREEMENT", "CNC"):
        return False

    # Determine the next EOM cycle to process.
    if liab.get("last_accrual_cycle_date"):
        last = parse_iso(liab["last_accrual_cycle_date"])
        next_cycle = end_of_month(add_one_month(last))
    else:
        # First cycle is the EOM of the assessment_date month.
        assessment_dt = parse_iso(liab["assessment_date"])
        next_cycle = end_of_month(assessment_dt)

    any_applied = False
    while next_cycle <= current_eom_dt:
        base = (
            liab["original_assessed_amount_cents"]
            + liab.get("accrued_interest_cents", 0)
            + liab.get("accrued_penalty_cents", 0)
            - liab.get("payments_applied_cents", 0)
        )
        if base < 0:
            base = 0

        interest = interest_for_cycle(base)
        penalty = penalty_for_cycle(base, liab["status"])

        liab["accrued_interest_cents"] = liab.get("accrued_interest_cents", 0) + interest
        liab["accrued_penalty_cents"] = liab.get("accrued_penalty_cents", 0) + penalty
        liab["last_accrual_cycle_date"] = fmt(next_cycle)
        recompute_balance(liab)
        any_applied = True

        next_cycle = end_of_month(add_one_month(next_cycle))

    if any_applied:
        bump_version(liab)
    return any_applied


# ---------------------------------------------------------------------------
# Sweep entry point
# ---------------------------------------------------------------------------

def run_sweep() -> dict:
    """Apply all deferred actions. Returns a summary dictionary (informational)."""
    summary = {
        "accrued_liabilities": 0,
        "defaulted_agreements": 0,
        "expired_liabilities": 0,
        "expired_cnc_statuses": 0,
    }

    now_dt = CLOCK.now()
    current_eom = end_of_month(now_dt)

    # 1. Monthly accrual
    for liab in list(STORE.tax_liabilities.values()):
        if _accrue_liability(liab, current_eom):
            summary["accrued_liabilities"] += 1

    affected_taxpayers = set()

    # 2. Missed-payment detection + new-liability default trigger
    for ia in list(STORE.installment_agreements.values()):
        if ia["status"] != "ACTIVE":
            continue
        # Increment missed_payment_count whenever next_due_date < now (treated as a missed cycle)
        next_due = parse_iso(ia["next_due_date"])
        if next_due < now_dt:
            # Count how many missed cycles passed (each ~30-day period since next_due)
            elapsed = now_dt - next_due
            missed_cycles = max(1, int(elapsed.total_seconds() // (30 * 86400)) + 1)
            ia["missed_payment_count"] = ia.get("missed_payment_count", 0) + missed_cycles
            bump_version(ia)

        # Default trigger: missed_payment_count >= 3 OR new OPEN liability assessed after activation_date
        activation = parse_iso(ia.get("activation_date") or ia["created_at"])
        has_new_open = any(
            l["taxpayer_id"] == ia["taxpayer_id"]
            and l["status"] == "OPEN"
            and l["id"] not in ia["liability_ids"]
            and parse_iso(l["created_at"]) >= activation
            for l in STORE.tax_liabilities.values()
        )
        if ia["missed_payment_count"] >= 3 or has_new_open:
            _default_agreement(ia)
            affected_taxpayers.add(ia["taxpayer_id"])
            summary["defaulted_agreements"] += 1

    # 3. CSED expiration
    for liab in list(STORE.tax_liabilities.values()):
        if liab["status"] not in ("OPEN", "CNC"):
            continue
        eff = parse_iso(liab["csed_effective_date"])
        if now_dt >= eff:
            liab["current_balance_cents"] = 0
            set_status(liab, "EXPIRED")
            affected_taxpayers.add(liab["taxpayer_id"])
            summary["expired_liabilities"] += 1

    if summary["expired_liabilities"]:
        release_check(dominant_cause="CSED_EXPIRED")

    # 4. CNC review-due expiration
    for cnc in list(STORE.cnc_statuses.values()):
        if cnc["status"] != "ACTIVE":
            continue
        review_due = parse_iso(cnc["review_due_date"])
        if now_dt >= review_due:
            _expire_cnc(cnc)
            affected_taxpayers.add(cnc["taxpayer_id"])
            summary["expired_cnc_statuses"] += 1

    for tp_id in affected_taxpayers:
        refresh_taxpayer_aggregates(tp_id)

    # Always refresh taxpayer aggregates touched by accrual
    for tp_id in {l["taxpayer_id"] for l in STORE.tax_liabilities.values()}:
        refresh_taxpayer_aggregates(tp_id)

    return summary


def _default_agreement(ia: dict) -> None:
    ia["status"] = "DEFAULTED"
    bump_version(ia)
    # Open INSTALLMENT_PENDING tolling event on each covered liability (if not already open)
    for lid in ia["liability_ids"]:
        liab = STORE.tax_liabilities.get(lid)
        if liab is None:
            continue
        # Only open if no open one already
        from app.services.csed import _open_event_of_kind  # local import to avoid cycle
        if _open_event_of_kind(lid, "INSTALLMENT_PENDING") is None:
            try:
                open_event(lid, "INSTALLMENT_PENDING", source_ref=ia["id"])
            except Exception:
                pass


def _expire_cnc(cnc: dict) -> None:
    cnc["status"] = "EXPIRED"
    bump_version(cnc)
    for lid in cnc["liability_ids"]:
        liab = STORE.tax_liabilities.get(lid)
        if liab is None:
            continue
        if liab["status"] == "CNC":
            set_status(liab, "OPEN")
        close_events_of_kind(lid, "CNC_HARDSHIP")
