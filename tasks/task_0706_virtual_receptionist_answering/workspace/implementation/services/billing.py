"""Billing calculations and account-posture cascade.

All money is integer cents (PRD §2.9). Minute rounding is per-call CEIL before
summation (PRD §2.9, §3.7). Tier boundary uses an at-or-above comparison on the
integer unit index (PRD §2.9, §3.8).
"""
import math

from db import db
from common import touch


def ceil_minutes(seconds):
    """Round a single call's seconds up to whole minutes (CEIL_MINUTE).
    ceil(0) == 0 (PRD §2.9, §3.7)."""
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 60)


def tiered_overage_charge(consumed_units, included_units, plan):
    """billing_overage formula (SCAFFOLD §1.3 calc 2, PRD §3.8).

    overage_units = max(0, consumed - included)
    tier1_units = min(overage_units, T2 - 1)        # strictly below threshold
    tier2_units = max(0, overage_units - (T2 - 1))  # at/above threshold
    charge = tier1*R1 + tier2*R2
    Returns (overage_units, tier1_units, tier2_units, overage_charge_cents).
    """
    t2 = plan["overage_tier2_threshold"]
    r1 = plan["overage_rate_cents"]
    r2 = plan["overage_tier2_rate_cents"]
    overage_units = max(0, consumed_units - included_units)
    tier1_units = min(overage_units, t2 - 1)
    tier2_units = max(0, overage_units - (t2 - 1))
    charge = tier1_units * r1 + tier2_units * r2
    return overage_units, tier1_units, tier2_units, charge


def estimate_inflight_units(call, plan):
    """Forward-looking per-call estimate for an IN_PROGRESS/WRAP_UP call used by
    the provisional variant (PRD §3.8).

    PER_CALL => 1; PER_MINUTE => ceil(elapsed_seconds/60).
    For IN_PROGRESS, elapsed = now_epoch - start_second.
    For WRAP_UP, duration_seconds is already finalized.
    """
    if plan["billing_model"] == "PER_CALL":
        return 1
    if call["handling_status"] == "WRAP_UP":
        elapsed = call["duration_seconds"]
    else:  # IN_PROGRESS
        elapsed = max(0, db.clock.epoch_seconds() - call["start_second"])
    return ceil_minutes(elapsed)


def consumed_units_final(period):
    """Final variant consumed_units: billed_units of BILLED/ADJUSTED calls only
    (PRD §3.8)."""
    total = 0
    for c in db.calls.values():
        if c["_period_id"] == period["id"] and c["billing_status"] in ("BILLED", "ADJUSTED"):
            total += c["billed_units"]
    return total


def consumed_units_provisional(period):
    """Provisional variant: BILLED/ADJUSTED billed_units PLUS a forward-looking
    estimate for the account's calls currently IN_PROGRESS or WRAP_UP (PRD §3.8)."""
    plan = db.service_plans[period["plan_id"]]
    total = consumed_units_final(period)
    account_id = period["account_id"]
    for c in db.calls.values():
        if c["account_id"] != account_id:
            continue
        if c["handling_status"] in ("IN_PROGRESS", "WRAP_UP"):
            total += estimate_inflight_units(c, plan)
    return total


def recompute_period_final(period):
    """Recompute consumed/overage/charge under the FINAL variant and reconcile
    the period record (PRD §2.5, §3.8). Returns the period."""
    plan = db.service_plans[period["plan_id"]]
    consumed = consumed_units_final(period)
    overage_units, _t1, _t2, charge = tiered_overage_charge(
        consumed, period["included_units"], plan)
    changed = (
        period["consumed_units"] != consumed
        or period["overage_units"] != overage_units
        or period["overage_charge_cents"] != charge
    )
    period["consumed_units"] = consumed
    period["overage_units"] = overage_units
    period["overage_charge_cents"] = charge
    if changed:
        touch(period)
    return period


def provisional_breakdown(period):
    """Provisional overage breakdown for an OPEN period (PRD §3.8 overage-summary)."""
    plan = db.service_plans[period["plan_id"]]
    consumed = consumed_units_provisional(period)
    overage_units, tier1_units, tier2_units, charge = tiered_overage_charge(
        consumed, period["included_units"], plan)
    return {
        "consumed_units": consumed,
        "overage_units": overage_units,
        "tier1_units": tier1_units,
        "tier2_units": tier2_units,
        "overage_charge_cents": charge,
        "variant": "provisional",
    }


def call_charge(call, period):
    """Per-call charge at completion (PRD §3.7, SCAFFOLD §1.3 calc 1).

    billed_units depends on billing_model; charge_cents is the MARGINAL overage
    contribution of these units to the period's tiered charge, computed on the
    period's consumed_units immediately before this call is billed.
    Returns (billed_units, charge_cents).
    """
    plan = db.service_plans[period["plan_id"]]
    if plan["billing_model"] == "PER_CALL":
        billed_units = 1
    else:
        billed_units = ceil_minutes(call["duration_seconds"])

    prev_consumed = consumed_units_final(period)
    _u0, _a0, _b0, prev_overage = tiered_overage_charge(
        prev_consumed, period["included_units"], plan)
    _u1, _a1, _b1, new_overage = tiered_overage_charge(
        prev_consumed + billed_units, period["included_units"], plan)
    charge_cents = max(0, new_overage - prev_overage)
    return billed_units, charge_cents


# --- Account posture cascade (PRD §3.9) -------------------------------------
def apply_posture_cascade(account):
    """Re-derive account status from its OPEN billing period's overage, applying
    the forward and reverse transitions of PRD §3.9.

    Forward (from a final recompute that raises overage):
      overage_charge_cents >= hard_cap  => SUSPENDED (cascade-cancel appts)
      else overage_units > 0            => DELINQUENT
    Reverse (from a final recompute that lowers overage, e.g. adjust):
      below hard_cap & overage_units>0  => SUSPENDED -> DELINQUENT (reinstate)
      overage_units == 0                => -> ACTIVE
    Appointments cancelled during suspension are NOT restored.
    """
    period = db.billing_periods.get(account["current_period_id"])
    if period is None:
        return
    plan = db.service_plans[period["plan_id"]]
    hard_cap = plan["hard_cap_overage_cents"]
    charge = period["overage_charge_cents"]
    overage_units = period["overage_units"]
    current = account["status"]

    if charge >= hard_cap:
        # Crosses the hard cap => SUSPENDED (from ACTIVE or DELINQUENT).
        if current != "SUSPENDED":
            _set_status(account, "SUSPENDED")
            _cascade_cancel_appointments(account)
        return

    # Below the hard cap from here on.
    if overage_units > 0:
        if current == "SUSPENDED":
            # Reinstate SUSPENDED -> DELINQUENT (appts NOT restored).
            _set_status(account, "DELINQUENT")
        elif current == "ACTIVE":
            _set_status(account, "DELINQUENT")
        # already DELINQUENT => stays DELINQUENT
        return

    # overage_units == 0
    if current in ("DELINQUENT", "SUSPENDED"):
        _set_status(account, "ACTIVE")


def _set_status(account, status):
    account["status"] = status
    touch(account)


def _cascade_cancel_appointments(account):
    """On suspension, cancel every own appointment in REQUESTED/CONFIRMED/
    RESCHEDULE_REQUESTED, decrementing each slot's booked_count (PRD §3.9)."""
    cancellable = {"REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED"}
    for appt in db.appointments.values():
        if appt["account_id"] != account["id"]:
            continue
        if appt["status"] in cancellable:
            appt["status"] = "CANCELLED"
            touch(appt)
            slot = db.calendar_slots.get(appt["slot_id"])
            if slot is not None:
                _decrement_slot(slot)


def _decrement_slot(slot):
    """Decrement booked_count and recompute available_count (PRD §3.12)."""
    slot["booked_count"] = max(0, slot["booked_count"] - 1)
    slot["available_count"] = max(0, slot["capacity"] - slot["booked_count"])
    touch(slot)
