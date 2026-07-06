"""Assessment state-machine helpers — used both by /assessments/{id}/pay and by
the time-based sweep in clock.sweep_time_transitions."""

import db
from entities import bump
from services import calc


def transition_to_overdue(assessment, now_iso):
    """OPEN|PARTIALLY_PAID -> OVERDUE: stamp late_fee_cents from calc.late_fee, mark
    assessment updated. Caller runs Property/Homeowner recompute afterwards."""
    from clock import get_now
    now_dt = get_now()
    home_id = _owning_homeowner_id(assessment)
    standing = "GOOD_STANDING"
    if home_id:
        h = db.homeowners.get(home_id)
        if h:
            standing = h.get("standing", "GOOD_STANDING")
    fee = calc.late_fee(
        amount_due_cents=assessment["amount_due_cents"],
        amount_paid_cents=assessment["amount_paid_cents"],
        due_date_iso=assessment["due_date"],
        current_utc_dt=now_dt,
        homeowner_standing=standing,
    )
    assessment["late_fee_cents"] = fee
    assessment["status"] = "OVERDUE"
    bump(assessment, now_iso)


def restamp_late_fee(assessment, now_iso):
    """Payment reversal that drops a PAID assessment back to OVERDUE re-stamps late_fee."""
    from clock import get_now
    now_dt = get_now()
    home_id = _owning_homeowner_id(assessment)
    standing = "GOOD_STANDING"
    if home_id:
        h = db.homeowners.get(home_id)
        if h:
            standing = h.get("standing", "GOOD_STANDING")
    fee = calc.late_fee(
        amount_due_cents=assessment["amount_due_cents"],
        amount_paid_cents=assessment["amount_paid_cents"],
        due_date_iso=assessment["due_date"],
        current_utc_dt=now_dt,
        homeowner_standing=standing,
    )
    assessment["late_fee_cents"] = fee


def _owning_homeowner_id(assessment):
    prop = db.properties.get(assessment["property_id"])
    if not prop:
        return None
    return prop["homeowner_id"]
