"""Route stops: reorder, arrive, complete, attach and detach (PRD 3.4, 3.5, 3.7)."""

from flask import Blueprint

from core.auth import authenticate
from core.constants import (
    CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES,
    MINUTES_PER_DAY,
    REORDER_DIRECTIONS,
)
from core.errors import ApiError
from core.store import db
from core.validate import bad, body, enum, out_of_range, req_int, req_str
from domain.gates import (
    ELIGIBLE,
    gate1_farrier,
    gate2_route_open,
    gate3_client,
    gate4_horse_hold,
    gate5_appointment,
)
from domain.invoices import allocate_trip_fee
from domain.lookup import guard_stop, must, must_ref
from domain.rates import select_rate_card
from domain.reservations import apply_reservations_for_attach, check_van_stock_for_attach
from domain.routecalc import (
    appointments_of_stop,
    check_access_window,
    check_adjacency,
    check_capacity,
    recompute_stop_minutes,
    stops_of,
)
from domain.routeops import detach_appointment, settle_route
from domain.rollups import lines_of, recompute_estimate
from domain.scheduling import mint_reminders

from ._common import listing, single

bp = Blueprint("route_stops", __name__)

READ_ROLES = ("PlatformAdmin", "Dispatcher", "Farrier")


@bp.get("/route-stops")
def list_stops():
    return listing(
        "route_stops",
        {"route_id": "route_id", "barn_id": "barn_id", "status": "status"},
        READ_ROLES,
    )


@bp.get("/route-stops/<stop_id>")
def read_stop(stop_id):
    authenticate(READ_ROLES)
    stop = must("route_stops", stop_id)
    guard_stop(stop)
    return single(stop)


@bp.post("/route-stops/<stop_id>/reorder")
def reorder_stop(stop_id):
    authenticate(("Dispatcher",))
    stop = must("route_stops", stop_id)
    data = body()
    direction = data.get("direction")
    if not isinstance(direction, str) or not direction:
        bad("Field direction is required.")
    planned_start_minute = req_int(data, "planned_start_minute")
    enum(direction, REORDER_DIRECTIONS, "direction")
    if planned_start_minute < 0 or planned_start_minute >= MINUTES_PER_DAY:
        out_of_range("planned_start_minute must be at least 0 and below %d." % MINUTES_PER_DAY)

    route = db.get("routes", stop["route_id"])
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    gate2_route_open(route)

    target_index = stop["sequence_index"] + (-1 if direction == "EARLIER" else 1)
    sibling = None
    for candidate in stops_of(route, include_voided=False):
        if candidate["sequence_index"] == target_index:
            sibling = candidate
            break
    if sibling is None:
        raise ApiError("ERR_INVALID_STATE")

    barn = db.get("barns", stop["barn_id"])
    check_access_window(barn, planned_start_minute, stop["service_minutes"])

    overrides = {
        stop["id"]: {
            "sequence_index": sibling["sequence_index"],
            "planned_start_minute": planned_start_minute,
        },
        sibling["id"]: {"sequence_index": stop["sequence_index"]},
    }
    check_adjacency(route, overrides=overrides, focus_ids={stop["id"], sibling["id"]})

    stop["sequence_index"], sibling["sequence_index"] = (
        sibling["sequence_index"],
        stop["sequence_index"],
    )
    stop["planned_start_minute"] = planned_start_minute
    stop["end_minute"] = planned_start_minute + stop["service_minutes"]
    # Adjudication of friction 5 (second half): both exchanged stop rows advance
    # their own version.  Section 2.4 states without qualification that a row's
    # version "increases by exactly 1 on every mutation of that row", and both
    # rows genuinely mutate here (this stop's sequence_index and
    # planned_start_minute, the sibling's sequence_index), so the general rule
    # is applied on top of the route increment the side-effect list names.
    db.touch(stop)
    db.touch(sibling)
    db.touch(route)
    return single(stop)


@bp.post("/route-stops/<stop_id>/arrive")
def arrive_stop(stop_id):
    authenticate(("Farrier",))
    stop = must("route_stops", stop_id)
    guard_stop(stop)
    route = db.get("routes", stop["route_id"])
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    if stop["status"] != "PENDING" or route["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE")
    for other in stops_of(route):
        if other["sequence_index"] < stop["sequence_index"] and other["status"] not in (
            "COMPLETED",
            "VOIDED",
        ):
            raise ApiError("ERR_INVALID_STATE")
    stop["status"] = "ARRIVED"
    db.touch(stop)
    return single(stop)


@bp.post("/route-stops/<stop_id>/complete")
def complete_stop(stop_id):
    authenticate(("Farrier",))
    stop = must("route_stops", stop_id)
    guard_stop(stop)
    route = db.get("routes", stop["route_id"])
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    if stop["status"] != "ARRIVED":
        raise ApiError("ERR_INVALID_STATE")
    for appointment in appointments_of_stop(stop):
        if appointment["status"] in ("SCHEDULED", "CONFIRMED", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_STATE")
    select_rate_card(route["route_date"], required=True)
    stop["status"] = "COMPLETED"
    allocate_trip_fee(stop)
    db.touch(stop)
    return single(stop)


@bp.post("/route-stops/<stop_id>/appointments")
def attach_appointment(stop_id):
    authenticate(("Dispatcher",))
    stop = must("route_stops", stop_id)
    data = body()
    must_ref("appointments", data.get("appointment_id"))
    appointment_id = req_str(data, "appointment_id")
    expected_route_version = req_int(data, "expected_route_version")
    appointment = db.get("appointments", appointment_id)
    route = db.get("routes", stop["route_id"])

    # rung 24
    if expected_route_version != route["version"]:
        raise ApiError("ERR_STALE_ROUTE_VERSION")

    horse = db.get("horses", appointment["horse_id"])
    client = db.get("clients", horse["client_id"])
    farrier = db.get("farriers", route["farrier_id"])

    gate1_farrier(farrier)
    gate2_route_open(route)
    gate3_client(client)
    gate4_horse_hold(horse, appointment)
    gate5_appointment(appointment, ELIGIBLE["attach"])

    # rung 35 -- the credential check runs before every other domain rule here.
    allowed = CERT_LEVEL_TO_ALLOWED_SERVICE_TYPES[farrier["certification_level"]]
    for line in lines_of(appointment):
        if line["service_type"] not in allowed:
            raise ApiError("ERR_CREDENTIAL_INSUFFICIENT")

    # rung 42
    if stop["barn_id"] != horse["barn_id"]:
        raise ApiError("ERR_BARN_MISMATCH")

    projected_stop_minutes = stop["service_minutes"] + appointment["service_minutes"]
    barn = db.get("barns", stop["barn_id"])
    # rung 45
    check_access_window(barn, stop["planned_start_minute"], projected_stop_minutes)
    # rung 46
    check_adjacency(
        route,
        overrides={stop["id"]: {"service_minutes": projected_stop_minutes}},
        focus_ids={stop["id"]},
    )
    # rung 47
    if horse["requires_sedation"] and not appointment["vet_present"]:
        raise ApiError("ERR_SEDATION_VET_REQUIRED")
    # rungs 49 and 50
    check_capacity(route, appointment["service_units"], appointment["service_minutes"])
    # rung 51
    required = check_van_stock_for_attach(appointment, farrier["id"])
    # rung 53
    select_rate_card(appointment["scheduled_date"], required=True)

    appointment["route_stop_id"] = stop["id"]
    appointment["status"] = "SCHEDULED"
    apply_reservations_for_attach(appointment, farrier["id"], required)
    if recompute_stop_minutes(stop):
        db.touch(stop)
    mint_reminders(appointment)
    recompute_estimate(appointment, horse)
    db.touch(appointment)
    settle_route(route)
    return single(appointment)


@bp.delete("/route-stops/<stop_id>/appointments/<appointment_id>")
def detach_appointment_endpoint(stop_id, appointment_id):
    authenticate(("Dispatcher",))
    stop = must("route_stops", stop_id)
    appointment = db.get("appointments", appointment_id)
    if appointment is None or appointment.get("route_stop_id") != stop["id"]:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    route = db.get("routes", stop["route_id"])
    gate1_farrier(db.get("farriers", route["farrier_id"]))
    gate2_route_open(route)
    gate5_appointment(appointment, ELIGIBLE["detach"])

    detach_appointment(appointment, "UNROUTED")
    db.touch(appointment)
    settle_route(route)
    return single(appointment)
