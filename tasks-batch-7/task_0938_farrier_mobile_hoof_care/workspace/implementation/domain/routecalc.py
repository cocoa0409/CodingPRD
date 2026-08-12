"""Route meters, stop geometry and the temporal rules (PRD 3.4)."""

from core.constants import (
    ROUTE_COMMITTING_STATUSES,
    ROUTE_MAX_MINUTES_PER_DAY,
    ROUTE_MAX_UNITS_PER_DAY,
)
from core.errors import ApiError
from core.store import db, order_key


def stops_of(route, include_voided=True):
    rows = [s for s in db.route_stops.values() if s["route_id"] == route["id"]]
    if not include_voided:
        rows = [s for s in rows if s["status"] != "VOIDED"]
    rows.sort(key=order_key)
    return rows


def appointments_of_stop(stop):
    rows = [a for a in db.appointments.values() if a.get("route_stop_id") == stop["id"]]
    rows.sort(key=order_key)
    return rows


def recompute_stop_minutes(stop):
    """RouteStop.service_minutes is the sum over the appointments attached to it.

    The entity defines it without a status filter, so an appointment that stays
    attached after an on-site cancellation or a no-show keeps contributing.
    Returns True when the stop actually changed.
    """
    total = sum(a["service_minutes"] for a in appointments_of_stop(stop))
    end = stop["planned_start_minute"] + total
    changed = stop["service_minutes"] != total or stop["end_minute"] != end
    stop["service_minutes"] = total
    stop["end_minute"] = end
    return changed


def recompute_route_totals(route):
    """Recompute both meters and the stop count from scratch.

    Recomputing from scratch is what makes the reserve/release and capacity
    round-trip invariants hold exactly.  No version is advanced here; each
    operation records its own mutation steps.
    """
    active = stops_of(route, include_voided=False)
    units = 0
    minutes = 0
    for stop in active:
        minutes += stop["travel_minutes"]
        for appointment in appointments_of_stop(stop):
            if appointment["status"] in ROUTE_COMMITTING_STATUSES:
                units += appointment["service_units"]
                minutes += appointment["service_minutes"]
    before_units = route["committed_units"]
    route["committed_units"] = units
    route["committed_minutes"] = minutes
    route["stop_count"] = len(active)
    return before_units


def revert_planned_route_if_emptied(route, before_units):
    """A PLANNED route whose committed_units has FALLEN to zero reverts to DRAFT."""
    if (
        route["status"] == "PLANNED"
        and before_units > 0
        and route["committed_units"] == 0
    ):
        route["status"] = "DRAFT"
        db.touch(route)
        return True
    return False


def check_capacity(route, delta_units, delta_minutes):
    """Units first, minutes second; landing exactly on a cap is accepted."""
    if route["committed_units"] + delta_units > ROUTE_MAX_UNITS_PER_DAY:
        raise ApiError("ERR_ROUTE_UNIT_CAPACITY_EXCEEDED")
    if route["committed_minutes"] + delta_minutes > ROUTE_MAX_MINUTES_PER_DAY:
        raise ApiError("ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED")


def check_access_window(barn, planned_start_minute, service_minutes):
    """Containment: start at or after opening, end at or before closing."""
    if planned_start_minute < barn["access_open_minute"]:
        raise ApiError("ERR_OUTSIDE_ACCESS_WINDOW")
    if planned_start_minute + service_minutes > barn["access_close_minute"]:
        raise ApiError("ERR_OUTSIDE_ACCESS_WINDOW")


def _projection(stop, overrides):
    data = {
        "sequence_index": stop["sequence_index"],
        "planned_start_minute": stop["planned_start_minute"],
        "service_minutes": stop["service_minutes"],
        "travel_minutes": stop["travel_minutes"],
    }
    data.update(overrides.get(stop["id"], {}))
    data["end_minute"] = data["planned_start_minute"] + data["service_minutes"]
    return data


def check_adjacency(route, overrides=None, extra=None, focus_ids=None):
    """Buffered adjacency between stops whose sequence_index differs by one.

    ``overrides`` projects changed values onto existing stops; ``extra`` adds a
    not-yet-persisted stop.  Only pairs touching ``focus_ids`` are policed, so a
    pre-existing violation elsewhere on the route never blocks an unrelated
    write.
    """
    overrides = overrides or {}
    projected = []
    for stop in stops_of(route, include_voided=False):
        item = _projection(stop, overrides)
        item["id"] = stop["id"]
        projected.append(item)
    if extra:
        item = dict(extra)
        item["end_minute"] = item["planned_start_minute"] + item["service_minutes"]
        projected.append(item)
    by_index = {}
    for item in projected:
        by_index.setdefault(item["sequence_index"], []).append(item)
    for index, items in by_index.items():
        later_items = by_index.get(index + 1, [])
        for earlier in items:
            for later in later_items:
                if focus_ids is not None and not (
                    earlier.get("id") in focus_ids or later.get("id") in focus_ids
                ):
                    continue
                if later["planned_start_minute"] < earlier["end_minute"] + later["travel_minutes"]:
                    raise ApiError("ERR_STOP_TIME_CONFLICT")
