"""RouteStop creation/completion and capacity/spacing rules (scaffold §1.2, PRD §3.7)."""
from datetime import timedelta

import db
import errors
import lookups
from errors import err


def create_route_stop(route, case, window_start_at, window_minutes):
    """POST /route-stops (PRD §3.7). Capacity + buffered-window checks.

    Validation precedence per scaffold: ERR_ROUTE_WINDOW_CONFLICT (priority 13,
    409) before ERR_ROUTE_AT_CAPACITY (priority 14, 422).
    """
    window_end_at = window_start_at + timedelta(minutes=window_minutes)

    # ERR_ROUTE_WINDOW_CONFLICT (priority 13): new stop's window expanded by
    # buffer_minutes on BOTH sides must not overlap any non-CANCELLED stop's
    # (unexpanded) window on the same route. Windows are CLOSED intervals.
    buffer = timedelta(minutes=route["buffer_minutes"])
    expanded_start = window_start_at - buffer
    expanded_end = window_end_at + buffer
    for s in lookups.case_route_stops_on_route(route["id"]):
        if s["status"] == "CANCELLED":
            continue
        # closed-interval overlap: expanded new stop vs existing unexpanded stop.
        if expanded_start <= s["window_end_at"] and s["window_start_at"] <= expanded_end:
            raise err(errors.ERR_ROUTE_WINDOW_CONFLICT,
                      "Route stop window conflicts with an existing stop.")

    # ERR_ROUTE_AT_CAPACITY (priority 14): stop_count already equals max_stops.
    if route["stop_count"] >= route["max_stops"]:
        raise err(errors.ERR_ROUTE_AT_CAPACITY, "Route is at capacity.")

    stop = db.stamp_create({
        "id": db.new_id(),
        "courier_route_id": route["id"],
        "case_id": case["id"],
        "window_start_at": window_start_at,
        "window_minutes": window_minutes,
        "window_end_at": window_end_at,
        "status": "PLANNED",
    })
    db.route_stops[stop["id"]] = stop

    # Increment route.stop_count (computed = non-CANCELLED stops attached).
    route["stop_count"] += 1
    db.touch(route)
    return stop


def complete_stop(stop):
    """POST /route-stops/{id}/complete — PLANNED -> COMPLETED (PRD §3.7)."""
    if stop["status"] != "PLANNED":
        raise err(errors.ERR_INVALID_STATE, "Route stop is not PLANNED.")
    stop["status"] = "COMPLETED"
    db.touch(stop)
    return stop
