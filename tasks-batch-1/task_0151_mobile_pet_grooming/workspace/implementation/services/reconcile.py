"""Derived-field reconciliation (PRD §2.6, §3.4, §3.9)."""
from datetime import timedelta

import db
import clock
from services import calc


def recompute_vaccination_status(pet):
    """VALID iff a non-expired RABIES record exists relative to current clock."""
    now = clock.now()
    valid = False
    for rec in db.vaccination_records.values():
        if rec["pet_id"] != pet["id"]:
            continue
        if rec["vaccine_type"] != "RABIES":
            continue
        if rec["expires_on"] > now:
            valid = True
            break
    pet["vaccination_status"] = "VALID" if valid else "EXPIRED"
    return pet["vaccination_status"]


def reconcile_muzzle(pet):
    pet["muzzle_required"] = (pet["behavioral_flag"] == "AGGRESSIVE")


# ---------------------------------------------------------------------------
# Route load reconciliation (PRD §3.4)
# booked_minutes = sum over non-VOIDED stops of (scheduled_minutes + TRAVEL_BUFFER_MIN)
# ---------------------------------------------------------------------------
COUNTED_STOP_STATUSES = {"RESERVED", "SERVICED", "NO_SHOW"}


def recompute_booked_minutes(route_day):
    total = 0
    for stop in db.route_stops.values():
        if stop["route_day_id"] != route_day["id"]:
            continue
        if stop["status"] in COUNTED_STOP_STATUSES:
            total += stop["scheduled_minutes"] + calc.TRAVEL_BUFFER_MIN
    route_day["booked_minutes"] = total
    return total


# ---------------------------------------------------------------------------
# Strike accounting (PRD §3.9)
# Count non-WAIVED NO_SHOW + late LATE_CANCEL fee charges whose triggering
# appointment's reserved slot_start is within trailing STRIKE_WINDOW_DAYS.
# ---------------------------------------------------------------------------
def _strike_slot_start(fee):
    """The reserved slot_start of the appointment that triggered this fee, or None."""
    appt = db.appointments.get(fee["appointment_id"])
    if appt is None:
        return None
    stop = db.route_stops.get(appt.get("route_stop_id"))
    if stop is None:
        return None
    return stop["slot_start"]


def recompute_customer_strikes(customer):
    now = clock.now()
    window_floor = now - timedelta(days=calc.STRIKE_WINDOW_DAYS)
    count = 0
    for fee in db.fee_charges.values():
        if fee["customer_id"] != customer["id"]:
            continue
        if fee["settlement_status"] == "WAIVED":
            continue
        if fee["fee_type"] not in ("NO_SHOW", "LATE_CANCEL"):
            continue
        slot_start = _strike_slot_start(fee)
        if slot_start is None:
            continue
        # window boundary inclusive at exactly STRIKE_WINDOW_DAYS ago
        if slot_start >= window_floor:
            count += 1
    customer["no_show_strikes"] = count
    customer["account_status"] = (
        "SUSPENDED" if count >= calc.STRIKE_SUSPEND_THRESHOLD else "ACTIVE"
    )
    return count


def recompute_outstanding_fees(customer):
    total = 0
    for fee in db.fee_charges.values():
        if fee["customer_id"] != customer["id"]:
            continue
        if fee["settlement_status"] == "PENDING":
            total += fee["amount_cents"]
    customer["outstanding_fee_cents"] = total
    return total
