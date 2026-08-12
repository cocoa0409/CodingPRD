"""Routes and route stops (PRD 3.3, 3.4)."""

from flask import Blueprint, g

from core import clock, db, gates
from core.auth import READ_ROLES, authenticate, authorize, require_owner
from core.constants import (
    MINUTES_PER_DAY,
    MIN_STOP_SERVICE_MINUTES,
    ROUTE_STOP_BUFFER_MINUTES,
    STAT_STOP_SERVICE_MINUTES,
    STOP_PRIORITY_ENUM,
    TRIP_FEE_CENTS,
)
from core.errors import ApiError
from core.validate import (
    body,
    enum_value,
    fail,
    opt_str,
    req_id,
    req_int,
    req_str,
)
from routes.common import apply_filters, fk, listing, need, one
from services import cascades, derive

bp = Blueprint("routing", __name__)


# ==========================================================================
# Route
# ==========================================================================

@bp.post("/routes")
def create_route():
    authenticate()
    authorize("Scheduler")
    data = body()
    # rung 4 — body foreign keys in the order the endpoint lists them
    unit = fk(data, "mobile_unit_id", "mobile_units", "ERR_RECORD_NOT_FOUND")
    technician = fk(data, "technician_id", "technicians", "ERR_RECORD_NOT_FOUND")
    # rung 5
    req_id(data, "mobile_unit_id")
    req_id(data, "technician_id")
    service_date = req_str(data, "service_date")
    if clock.parse_date(service_date) is None:
        fail("Field 'service_date' must be a YYYY-MM-DD calendar date.")
    start = req_int(data, "shift_start_minute", minimum=0, maximum=MINUTES_PER_DAY)
    end = req_int(data, "shift_end_minute", minimum=0, maximum=MINUTES_PER_DAY)
    if start >= end:
        fail("shift_start_minute must be strictly less than shift_end_minute.")
    # rung 23 — status limb only; a route names no modality, so certification
    # is deliberately NOT checked here.
    if technician["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE")

    rec = db.new_record()
    rec.update(
        {
            "mobile_unit_id": unit["id"],
            "technician_id": technician["id"],
            "service_date": service_date,
            "shift_start_minute": start,
            "shift_end_minute": end,
            "status": "DRAFT",
            "published_at": None,
            "dispatched_at": None,
            "completed_at": None,
        }
    )
    db.insert("routes", rec)
    return one("routes", rec, 201)


@bp.get("/routes/<route_id>")
def get_route(route_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("routes", need("routes", route_id, "ERR_ROUTE_NOT_FOUND"))


@bp.get("/routes")
def list_routes():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("routes")
    rows = apply_filters(
        rows,
        {
            "mobile_unit_id": "mobile_unit_id",
            "technician_id": "technician_id",
            "service_date": "service_date",
            "status": "status",
        },
    )
    return listing("routes", rows)


def _counted(route):
    return derive.counted_stops(route)


def _window_conflicts(route, arrival, service, ignore_ids=()):
    p_start = arrival
    p_end = arrival + service
    for s in _counted(route):
        if s["id"] in ignore_ids:
            continue
        x_start = s["planned_arrival_minute"]
        x_end = x_start + s["service_minutes"]
        if (
            p_start < x_end + ROUTE_STOP_BUFFER_MINUTES
            and x_start < p_end + ROUTE_STOP_BUFFER_MINUTES
        ):
            return True
    return False


def _capacity(route, unit, proposed_load):
    counted = _counted(route)
    n = len(counted)
    occupied = sum(s["drive_minutes_from_prev"] + s["service_minutes"] for s in counted)
    new_n = n + 1
    buffer_total = ROUTE_STOP_BUFFER_MINUTES * max(0, new_n - 1)
    window = route["shift_end_minute"] - route["shift_start_minute"]
    budget = min(window, unit["max_shift_minutes"])
    count_ok = new_n <= unit["max_stops"]
    minutes_ok = (occupied + proposed_load + buffer_total) <= budget
    return count_ok, minutes_ok


def _pick_victim(route, already=()):
    """PLANNED + ROUTINE only; latest planned_arrival_minute first, ties by the
    earlier created_at.  Identifiers are never part of the ordering."""
    eligible = [
        s
        for s in derive.stops_of_route(route)
        if s["status"] == "PLANNED"
        and s["stop_priority"] == "ROUTINE"
        and s["id"] not in already
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda s: (-s["planned_arrival_minute"], s["created_at"], s["_seq"]))
    return eligible[0]


@bp.post("/routes/<route_id>/stops")
def add_stop(route_id):
    authenticate()
    authorize("Scheduler")
    route = need("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    data = body()
    # rung 4 — body FKs
    clinic = fk(data, "clinic_id", "clinics", "ERR_CLINIC_NOT_FOUND")
    # rung 5
    req_id(data, "clinic_id")
    arrival = req_int(data, "planned_arrival_minute", minimum=0, maximum=MINUTES_PER_DAY)
    payload_service = req_int(data, "service_minutes", minimum=0)
    drive = req_int(data, "drive_minutes_from_prev", minimum=0)
    priority = opt_str(data, "stop_priority", "ROUTINE")
    expected = req_int(data, "expected_route_version")
    # rung 6
    enum_value(priority, STOP_PRIORITY_ENUM, "stop_priority")
    # rung 7
    if expected != route["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rungs 8-12 (G1 for the bump cascade is consulted per victim below)
    gates.g3_unit_in_service(route)
    gates.g5_route_not_completed(route)

    unit = db.get("mobile_units", route["mobile_unit_id"])

    # A STAT stop's service time is forced to 30 BEFORE rung 40 and every later
    # rung runs; rung 40's first limb nevertheless inspects the payload value.
    effective_service = (
        STAT_STOP_SERVICE_MINUTES if priority == "STAT" else payload_service
    )

    # rung 40
    if payload_service < MIN_STOP_SERVICE_MINUTES:
        raise ApiError("ERR_STOP_SERVICE_MINUTES_TOO_SHORT")
    if (
        arrival < route["shift_start_minute"]
        or arrival + effective_service > route["shift_end_minute"]
    ):
        raise ApiError("ERR_STOP_OUTSIDE_SHIFT_WINDOW")
    # rung 41
    if _window_conflicts(route, arrival, effective_service):
        raise ApiError("ERR_STOP_WINDOW_CONFLICT")
    # rung 42 — whole-calendar-day granularity, across every route and unit
    for s in db.all_rows("route_stops"):
        if s["clinic_id"] != clinic["id"]:
            continue
        if s["status"] not in ("PLANNED", "EN_ROUTE", "ARRIVED", "SERVICED"):
            continue
        other_route = db.get("routes", s["route_id"])
        if other_route is not None and other_route["service_date"] == route["service_date"]:
            raise ApiError("ERR_CLINIC_STOP_ALREADY_SCHEDULED")

    # rungs 43/44 with the STAT bump fallback
    proposed_load = effective_service + drive
    count_ok, minutes_ok = _capacity(route, unit, proposed_load)
    if not (count_ok and minutes_ok):
        if priority == "ROUTINE":
            raise ApiError(
                "ERR_ROUTE_STOP_CAP_EXCEEDED"
                if not count_ok
                else "ERR_ROUTE_SHIFT_MINUTES_EXCEEDED"
            )
        bumped = []
        bumped_ids = set()
        for _ in range(unit["max_stops"]):
            victim = _pick_victim(route, bumped_ids)
            if victim is None:
                break
            # Gate G1 refuses the whole insertion before anything is written when
            # the bump cascade would reverse a line on a FINALIZED invoice.
            cascades.guard_provider_cancel_gate_g1(victim)
            bumped.append(victim)
            bumped_ids.add(victim["id"])
            # The victim is not bumped until the cascade runs below, so simulate
            # its removal for the recomputation.
            counted = [s for s in _counted(route) if s["id"] not in bumped_ids]
            n = len(counted)
            occupied = sum(
                s["drive_minutes_from_prev"] + s["service_minutes"] for s in counted
            )
            new_n = n + 1
            buffer_total = ROUTE_STOP_BUFFER_MINUTES * max(0, new_n - 1)
            window = route["shift_end_minute"] - route["shift_start_minute"]
            budget = min(window, unit["max_shift_minutes"])
            count_ok = new_n <= unit["max_stops"]
            minutes_ok = (occupied + proposed_load + buffer_total) <= budget
            if count_ok and minutes_ok:
                break
        if not (count_ok and minutes_ok):
            raise ApiError(
                "ERR_ROUTE_STOP_CAP_EXCEEDED"
                if not count_ok
                else "ERR_ROUTE_SHIFT_MINUTES_EXCEEDED"
            )
    else:
        bumped = []

    stop = db.new_record()
    stop.update(
        {
            "route_id": route["id"],
            "clinic_id": clinic["id"],
            "bumped_by_stop_id": None,
            "_sequence": None,
            "planned_arrival_minute": arrival,
            "service_minutes": effective_service,
            "drive_minutes_from_prev": drive,
            "stop_priority": priority,
            "status": "PLANNED",
            "trip_fee_cents": TRIP_FEE_CENTS,
            "arrived_at": None,
            "departed_at": None,
            "cancel_reason": None,
        }
    )
    db.insert("route_stops", stop)

    for victim in bumped:
        cascades.bump_stop(victim, stop["id"])

    derive.resequence_route(route)
    db.touch(route)
    return one("route_stops", stop, 201)


@bp.post("/routes/<route_id>/publish")
def publish_route(route_id):
    authenticate()
    authorize("Scheduler")
    route = need("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    gates.g3_unit_in_service(route)
    gates.g5_route_not_completed(route)
    if route["status"] != "DRAFT":
        raise ApiError("ERR_ROUTE_INVALID_STATE")
    planned = [s for s in derive.stops_of_route(route) if s["status"] == "PLANNED"]
    if not planned:
        raise ApiError("ERR_ROUTE_HAS_NO_STOPS")
    route["status"] = "PUBLISHED"
    route["published_at"] = clock.now()
    derive.resequence_route(route)
    db.touch(route)
    return one("routes", route)


@bp.post("/routes/<route_id>/unpublish")
def unpublish_route(route_id):
    authenticate()
    authorize("Scheduler")
    route = need("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    gates.g5_route_not_completed(route)
    if route["status"] != "PUBLISHED":
        raise ApiError("ERR_ROUTE_INVALID_STATE")
    for s in derive.stops_of_route(route):
        if s["status"] in ("EN_ROUTE", "ARRIVED", "SERVICED"):
            raise ApiError("ERR_STOP_INVALID_STATE")
    route["status"] = "DRAFT"
    route["published_at"] = None
    db.touch(route)
    return one("routes", route)


@bp.post("/routes/<route_id>/dispatch")
def dispatch_route(route_id):
    authenticate()
    authorize("FieldTech")
    route = need("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    require_owner(g.user_id == route["technician_id"])
    gates.g3_unit_in_service(route)
    gates.g5_route_not_completed(route)
    if route["status"] != "PUBLISHED":
        raise ApiError("ERR_ROUTE_INVALID_STATE")
    technician = db.get("technicians", route["technician_id"])
    if technician is None or technician["status"] != "ACTIVE":
        raise ApiError("ERR_TECHNICIAN_INACTIVE")

    route["status"] = "DISPATCHED"
    route["dispatched_at"] = clock.now()
    db.touch(route)
    for s in derive.stops_of_route(route):
        if s["status"] == "PLANNED":
            s["status"] = "EN_ROUTE"
            db.touch(s)
    derive.resequence_route(route)
    return one("routes", route)


@bp.post("/routes/<route_id>/complete")
def complete_route(route_id):
    authenticate()
    authorize("FieldTech")
    route = need("routes", route_id, "ERR_ROUTE_NOT_FOUND")
    require_owner(g.user_id == route["technician_id"])
    gates.g5_route_not_completed(route)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_INVALID_STATE")
    for s in derive.stops_of_route(route):
        if s["status"] in ("EN_ROUTE", "ARRIVED"):
            raise ApiError("ERR_STOP_INVALID_STATE")
    route["status"] = "COMPLETED"
    route["completed_at"] = clock.now()
    db.touch(route)
    return one("routes", route)


# ==========================================================================
# RouteStop
# ==========================================================================

@bp.get("/route-stops/<stop_id>")
def get_stop(stop_id):
    authenticate()
    authorize(*READ_ROLES)
    return one("route_stops", need("route_stops", stop_id, "ERR_STOP_NOT_FOUND"))


@bp.get("/route-stops")
def list_stops():
    authenticate()
    authorize(*READ_ROLES)
    rows = db.all_rows("route_stops")
    rows = apply_filters(
        rows,
        {
            "route_id": "route_id",
            "clinic_id": "clinic_id",
            "bumped_by_stop_id": "bumped_by_stop_id",
            "status": "status",
        },
    )
    return listing("route_stops", rows)


@bp.post("/route-stops/<stop_id>/arrive")
def arrive_stop(stop_id):
    authenticate()
    authorize("FieldTech")
    stop = need("route_stops", stop_id, "ERR_STOP_NOT_FOUND")
    route = derive.route_of_stop(stop)
    require_owner(route is not None and g.user_id == route["technician_id"])
    gates.g5_route_not_completed(route)
    if route["status"] != "DISPATCHED":
        raise ApiError("ERR_ROUTE_INVALID_STATE")
    if stop["status"] != "EN_ROUTE":
        raise ApiError("ERR_STOP_INVALID_STATE")

    stop["status"] = "ARRIVED"
    stop["arrived_at"] = clock.now()
    db.touch(stop)
    for appt in derive.appointments_of_stop(stop):
        if appt["status"] == "SCHEDULED":
            appt["status"] = "IN_PROGRESS"
            db.touch(appt)
    derive.resequence_route(route)
    return one("route_stops", stop)


@bp.post("/route-stops/<stop_id>/depart")
def depart_stop(stop_id):
    authenticate()
    authorize("FieldTech")
    stop = need("route_stops", stop_id, "ERR_STOP_NOT_FOUND")
    route = derive.route_of_stop(stop)
    require_owner(route is not None and g.user_id == route["technician_id"])
    gates.g5_route_not_completed(route)
    if stop["status"] != "ARRIVED":
        raise ApiError("ERR_STOP_INVALID_STATE")
    # Adjudication of friction 9: the "no study still ORDERED" precondition has no
    # dedicated code, so it surfaces under rung 17 as ERR_STOP_INVALID_STATE —
    # the reading PRD 3.4 states outright ("no other code in this document covers
    # the case").  Routing it anywhere else would emit an identifier §5 does not
    # license for this endpoint.
    for study in derive.studies_at_stop(stop):
        if study["workflow_status"] == "ORDERED":
            raise ApiError("ERR_STOP_INVALID_STATE")

    stop["status"] = "SERVICED"
    stop["departed_at"] = clock.now()
    db.touch(stop)
    for appt in derive.appointments_of_stop(stop):
        if appt["status"] == "IN_PROGRESS":
            appt["status"] = "COMPLETED"
            db.touch(appt)
    return one("route_stops", stop)


@bp.post("/route-stops/<stop_id>/cancel")
def cancel_stop(stop_id):
    authenticate()
    authorize("Scheduler")
    stop = need("route_stops", stop_id, "ERR_STOP_NOT_FOUND")
    data = body()
    cancel_reason = req_str(data, "cancel_reason")
    route = derive.route_of_stop(stop)
    gates.g5_route_not_completed(route)
    if stop["status"] not in ("PLANNED", "EN_ROUTE"):
        raise ApiError("ERR_STOP_INVALID_STATE")
    cascades.guard_provider_cancel_gate_g1(stop)
    cascades.cancel_stop(stop, cancel_reason)
    derive.resequence_route(route)
    return one("route_stops", stop)
