"""Shared route operations: detaching a visit and cancelling a whole route."""

from core.store import db, order_key

from .reservations import release_reservations
from .routecalc import (
    appointments_of_stop,
    recompute_route_totals,
    recompute_stop_minutes,
    revert_planned_route_if_emptied,
    stops_of,
)


def detach_appointment(appointment, new_status="UNROUTED"):
    """Reverse an attachment exactly: reservations released, meters restored."""
    stop = db.get("route_stops", appointment.get("route_stop_id"))
    appointment["route_stop_id"] = None
    if new_status is not None:
        appointment["status"] = new_status
    release_reservations(appointment)
    route = None
    if stop is not None:
        if recompute_stop_minutes(stop):
            db.touch(stop)
        route = db.get("routes", stop["route_id"])
    return stop, route


def settle_route(route, force=False):
    """Recompute a route's meters and record one mutation step if they moved."""
    if route is None:
        return
    snapshot = (route["committed_units"], route["committed_minutes"], route["stop_count"])
    before = recompute_route_totals(route)
    changed = snapshot != (
        route["committed_units"],
        route["committed_minutes"],
        route["stop_count"],
    )
    if changed or force:
        db.touch(route)
    revert_planned_route_if_emptied(route, before)


def cancel_route(route):
    """Void the PENDING stops, free every attachment and release the reservations."""
    for stop in stops_of(route):
        if stop["status"] != "PENDING":
            continue
        for appointment in sorted(appointments_of_stop(stop), key=order_key):
            appointment["route_stop_id"] = None
            appointment["status"] = "UNROUTED"
            release_reservations(appointment)
            db.touch(appointment)
        recompute_stop_minutes(stop)
        stop["status"] = "VOIDED"
        db.touch(stop)
    route["status"] = "CANCELLED"
    recompute_route_totals(route)
    db.touch(route)
