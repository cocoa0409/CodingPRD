"""Cross-entity domain services: service-area resolution, route stop counting,
sequencing, and controlled-stock reconciliation.
"""
import db
import models
from calculations import round_half_up_1dp
from decimal import Decimal


def resolve_active_service_area(home_zip):
    """Return the ACTIVE ServiceArea whose zip_code matches home_zip, else None."""
    for area in db.service_areas.values():
        if area["zip_code"] == home_zip and area["status"] == "ACTIVE":
            return area
    return None


def stops_for_route(route_day_id):
    return [s for s in db.route_stops.values() if s["route_day_id"] == route_day_id]


def recompute_stop_count(route_day):
    """stop_count = count of stops in {PLANNED, ARRIVED, SERVICED}. Mutation."""
    counted = {"PLANNED", "ARRIVED", "SERVICED"}
    n = sum(
        1 for s in stops_for_route(route_day["id"]) if s["status"] in counted
    )
    route_day["stop_count"] = n
    models.touch(route_day)


def assign_sequence(route_day_id):
    """Assign 1-based sequence over non-SKIPPED stops, ordered by
    window_start ASC then created_at ASC (never id). Each touched stop is a
    mutation. SKIPPED stops keep their frozen sequence.
    """
    non_skipped = [
        s for s in stops_for_route(route_day_id) if s["status"] != "SKIPPED"
    ]
    non_skipped.sort(key=lambda s: (s["window_start"], s["created_at"], s.get("_seq", 0)))
    for i, stop in enumerate(non_skipped, start=1):
        if stop["sequence"] != i:
            stop["sequence"] = i
            models.touch(stop)


def logs_for_appointment(appointment_id):
    return [
        l for l in db.controlled_med_logs.values()
        if l["appointment_id"] == appointment_id
    ]


def estimates_for_appointment(appointment_id):
    return [
        e for e in db.estimates.values()
        if e["appointment_id"] == appointment_id
    ]


def linked_route_stop(appointment_id):
    """Return the RouteStop booking this appointment, if any."""
    for s in db.route_stops.values():
        if s["appointment_id"] == appointment_id:
            return s
    return None


def reconcile_controlled_balance(route_day):
    """Independent recount of vehicle controlled stock for this route's logs.

    Replays every ControlledMedLog whose appointment was serviced on this route,
    in created_at ASC (tie-break created_at, never id), subtracting amount_ml.
    Returns the expected remaining mL (1dp round-half-up) as a float.

    Starting point is the vehicle's controlled-stock snapshot captured at lock
    (RouteDay._controlled_stock_at_lock); both DISPENSE and WASTE consume drug.
    """
    appt_ids = {
        s["appointment_id"] for s in stops_for_route(route_day["id"])
    }
    logs = [
        l for l in db.controlled_med_logs.values()
        if l["appointment_id"] in appt_ids
    ]
    logs.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    consumed = Decimal("0")
    for l in logs:
        consumed += Decimal(str(l["amount_ml"]))
    starting = Decimal(str(route_day["_controlled_stock_at_lock"]))
    expected_remaining = round_half_up_1dp(starting - consumed)
    return expected_remaining
