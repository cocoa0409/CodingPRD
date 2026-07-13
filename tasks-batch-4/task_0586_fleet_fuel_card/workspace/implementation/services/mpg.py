"""Fuel economy (PRD §3.4 mpg_snapshot, §3.8 SEGMENT / ROLLING)."""
from util import dec, num, round_half_up
from services.store import txn_order_key, vehicle_transactions


def economy_window(vehicle_id):
    """AUTHORIZED-or-later, non-VOIDED transactions of the vehicle, ordered by
    purchased_at asc with ties broken by created_at asc (PRD §3.8)."""
    window = [t for t in vehicle_transactions(vehicle_id) if t["posting_status"] != "VOIDED"]
    return sorted(window, key=txn_order_key)


def all_vehicle_transactions(vehicle_id):
    """Every AUTHORIZED-or-later transaction of the vehicle (VOIDED included),
    ordered.  Used for current_odometer and for the previous-odometer lookup."""
    return sorted(vehicle_transactions(vehicle_id), key=txn_order_key)


def current_odometer(vehicle):
    txns = all_vehicle_transactions(vehicle["id"])
    if not txns:
        return num(dec(vehicle["starting_odometer"]))
    return num(dec(txns[-1]["odometer"]))


def mpg_exception(vehicle, mpg_value):
    """True when the economy figure falls below expected_mpg_min or above expected_mpg_max."""
    return bool(dec(mpg_value) < dec(vehicle["expected_mpg_min"])
                or dec(mpg_value) > dec(vehicle["expected_mpg_max"]))


def _round1(value):
    return float(round_half_up(value, 1))


def segment_mpg(vehicle):
    window = economy_window(vehicle["id"])
    if not window:
        return 0.0
    latest = window[-1]
    gallons = dec(latest["gallons"])
    if gallons == 0:
        return 0.0
    return _round1(dec(latest["segment_miles"]) / gallons)


def rolling_mpg(vehicle):
    window = economy_window(vehicle["id"])
    if not window:
        return 0.0
    total_miles = dec(window[-1]["odometer"]) - dec(window[0]["odometer"])
    total_gallons = sum((dec(t["gallons"]) for t in window), dec(0))
    if total_gallons == 0:
        return 0.0
    return _round1(total_miles / total_gallons)


def compute_mpg(vehicle, method):
    value = rolling_mpg(vehicle) if method == "ROLLING" else segment_mpg(vehicle)
    return {
        "method": method,
        "mpg": value,
        "exception": mpg_exception(vehicle, value),
    }
