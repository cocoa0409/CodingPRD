"""Calculations and derived-field recomputation."""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import touch

# --- service failure score constants ---
ATTEMPT_PENALTY = 10
ATTEMPT_ESCALATION = 5
HAZMAT_FAILURE_EXTRA = 8
REDELIVERY_RECOVERY_CREDIT = 6
RETURN_PENALTY = 20

# --- redelivery surcharge constants ---
SERVICE_BASE = {"GROUND": 300, "EXPRESS": 500, "PRIORITY": 800}
ATTEMPT_STEP = 150
SIGNATURE_EXTRA = 120
HAZMAT_MULT = Decimal("1.5")
MAX_ATTEMPTS = 3

# --- handling fee constants ---
HANDLING_BASE_CENTS = Decimal("50")
PER_KG_CENTS = Decimal("12.5")

# --- appointment buffer ---
APPOINTMENT_BUFFER_MIN = 30

# weight statuses
PLANNED_STATUSES = {"PENDING", "OUT_FOR_DELIVERY", "ATTEMPTED", "REDELIVERY_SCHEDULED", "DELIVERED"}
COMMITTED_STATUSES = {"PENDING", "OUT_FOR_DELIVERY", "ATTEMPTED", "REDELIVERY_SCHEDULED"}


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_route_metrics(route):
    """Recompute planned/committed weight and stop_count for a route (mutating it)."""
    planned = 0.0
    committed = 0.0
    count = 0
    for stop in db.stops.values():
        if stop["route_id"] != route["id"]:
            continue
        if stop["status"] != "CANCELLED":
            count += 1
        parcel = db.parcels.get(stop["parcel_id"])
        if parcel is None:
            continue
        w = parcel["weight_kg"]
        if stop["status"] in PLANNED_STATUSES:
            planned += w
        if stop["status"] in COMMITTED_STATUSES:
            committed += w
    route["planned_weight_kg"] = planned
    route["committed_weight_kg"] = committed
    route["stop_count"] = count


def recompute_center_sorted_count(center):
    if center is None:
        return
    cnt = 0
    for parcel in db.parcels.values():
        if parcel["status"] == "SORTED" and parcel.get("sorted_at_center_id") == center["id"]:
            cnt += 1
    center["sorted_count"] = cnt


def center_live_sorted_count(center_id):
    cnt = 0
    for parcel in db.parcels.values():
        if parcel["status"] == "SORTED" and parcel.get("sorted_at_center_id") == center_id:
            cnt += 1
    return cnt


def recompute_stop_attempt_count(stop):
    cnt = 0
    for a in db.attempts.values():
        if a["stop_id"] == stop["id"]:
            cnt += 1
    stop["attempt_count"] = cnt


def apply_attempt_penalty(driver, attempt_index, parcel):
    base = ATTEMPT_PENALTY
    escalation = ATTEMPT_ESCALATION * (attempt_index - 1)
    hazmat_extra = HAZMAT_FAILURE_EXTRA if parcel["hazmat_class"] != "NONE" else 0
    driver["failure_points"] = max(0, driver["failure_points"] + base + escalation + hazmat_extra)


def apply_recovery_credit(driver):
    driver["failure_points"] = max(0, driver["failure_points"] - REDELIVERY_RECOVERY_CREDIT)


def apply_return_penalty(driver):
    driver["failure_points"] = max(0, driver["failure_points"] + RETURN_PENALTY)


def compute_redelivery_surcharge(stop, parcel):
    """Compute this reschedule's surcharge (cents) and add to redelivery_fee_cents.

    reschedule_index = stop.attempt_count - 1 at moment of reschedule.
    """
    tier_base = SERVICE_BASE[parcel["service_level"]]
    reschedule_index = stop["attempt_count"] - 1
    escalated = tier_base + (ATTEMPT_STEP * reschedule_index)
    sig_extra = SIGNATURE_EXTRA if parcel["signature_required"] else 0
    hazmat_mult = HAZMAT_MULT if parcel["hazmat_class"] != "NONE" else Decimal("1")
    product = (Decimal(escalated) + Decimal(sig_extra)) * hazmat_mult
    this_surcharge = _round_half_up(product)
    stop["redelivery_fee_cents"] += this_surcharge
    return this_surcharge


def compute_manifest_total(route):
    """Round-per-line-item then sum. Stops in ascending sequence, tie created_at ASC."""
    stops = [s for s in db.stops.values()
             if s["route_id"] == route["id"] and s["status"] != "CANCELLED"]
    stops.sort(key=lambda s: (s["sequence"], s["created_at"]))
    total = 0
    for s in stops:
        parcel = db.parcels.get(s["parcel_id"])
        if parcel is None:
            continue
        raw = HANDLING_BASE_CENTS + Decimal(str(parcel["weight_kg"])) * PER_KG_CENTS
        line_fee = _round_half_up(raw)
        total += line_fee
    return total, len(stops)
