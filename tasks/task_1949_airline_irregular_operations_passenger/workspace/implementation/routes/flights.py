"""Flight CRUD + delay/cancel/depart/record-actuals + cabin inventory listing."""

from flask import Blueprint

import errors
from db import db
from middleware import authenticate, require_role
from response import success_list, success_object
from serializers import serialize_cabin_inventory, serialize_flight
from services.cascades import (
    run_cancel_cascade,
    run_misconnect_cascade,
    run_record_actuals,
)
from services.core import (
    crew_legality_reeval,
    recompute_event_affected,
    stamp_new,
    touch,
)
from validators import (
    get_json_body,
    opt_query_enum,
    pagination_params,
    req_datetime,
    req_int,
    req_string,
)

bp = Blueprint("flights", __name__)

FLIGHT_STATUSES = {"SCHEDULED", "DELAYED", "IN_FLIGHT", "ARRIVED", "CANCELLED"}
CABINS = {"ECONOMY", "PREMIUM", "BUSINESS", "FIRST"}
EVENT_DELAY_STATES = {"OPEN", "ASSESSING", "RECOVERY"}
EVENT_CANCEL_STATES = {"ASSESSING", "RECOVERY"}

FLIGHT_READ_ROLES = ["OpsController", "DutyManager", "ReaccommodationAgent",
                     "CrewScheduler", "FinanceProcessor", "OpsAdmin", "Passenger"]
FLIGHT_LIST_ROLES = ["OpsController", "DutyManager", "ReaccommodationAgent",
                     "CrewScheduler", "FinanceProcessor", "OpsAdmin"]


@bp.post("/irops/flights")
def create_flight():
    caller = authenticate()
    require_role(caller, ["OpsController"])
    body = get_json_body()
    flight_number = req_string(body, "flight_number")
    origin = req_string(body, "origin")
    destination = req_string(body, "destination")
    sched_dep = req_datetime(body, "sched_dep_utc")
    sched_arr = req_datetime(body, "sched_arr_utc")
    distance_km = req_int(body, "distance_km")
    operating_carrier = req_string(body, "operating_carrier")
    cabins = body.get("cabins")
    if cabins is None or not isinstance(cabins, list):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "cabins must be an array")
    if sched_arr <= sched_dep:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "sched_arr_utc must be strictly after sched_dep_utc")
    cabin_specs = []
    for entry in cabins:
        if not isinstance(entry, dict):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "cabins entries must be objects")
        cabin = entry.get("cabin")
        if not isinstance(cabin, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "cabin must be a string")
        if cabin not in CABINS:
            errors.raise_error(errors.ERR_INVALID_ENUM,
                               "cabin value %r outside declared enum domain" % cabin)
        capacity = entry.get("capacity")
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "capacity must be an integer")
        cabin_specs.append((cabin, capacity))
    f = stamp_new({
        "flight_number": flight_number,
        "origin": origin,
        "destination": destination,
        "sched_dep_utc": sched_dep,
        "sched_arr_utc": sched_arr,
        "orig_sched_dep_utc": sched_dep,
        "orig_sched_arr_utc": sched_arr,
        "act_dep_utc": None,
        "act_arr_utc": None,
        "distance_km": distance_km,
        "operating_carrier": operating_carrier,
        "flight_status": "SCHEDULED",
        "disruption_event_id": None,
        "cancelled_at": None,
        "crew_coverage_status": "CREW_SHORT",
    })
    db.flights[f["id"]] = f
    for cabin, capacity in cabin_specs:
        ci = stamp_new({
            "flight_id": f["id"],
            "cabin": cabin,
            "capacity": capacity,
            "seats_sold": 0,
            "interline_seats_committed": 0,
        })
        db.cabin_inventories[ci["id"]] = ci
    crew_legality_reeval(f)
    return success_object(serialize_flight(f), 201)


@bp.get("/irops/flights/<fid>")
def get_flight(fid):
    caller = authenticate()
    require_role(caller, FLIGHT_READ_ROLES)
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    return success_object(serialize_flight(f), 200)


@bp.get("/irops/flights")
def list_flights():
    from flask import request
    caller = authenticate()
    require_role(caller, FLIGHT_LIST_ROLES)
    status = opt_query_enum("flight_status", FLIGHT_STATUSES)
    event_id = request.args.get("disruption_event_id")
    limit, offset = pagination_params()
    items = sorted(db.flights.values(), key=lambda f: f["created_at"])
    if status is not None:
        items = [f for f in items if f["flight_status"] == status]
    if event_id is not None:
        items = [f for f in items if f["disruption_event_id"] == event_id]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_flight(f) for f in page], limit, offset, total)


@bp.get("/irops/flights/<fid>/cabin-inventories")
def list_cabin_inventories(fid):
    caller = authenticate()
    require_role(caller, FLIGHT_LIST_ROLES)
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    limit, offset = pagination_params()
    items = sorted(
        [ci for ci in db.cabin_inventories.values() if ci["flight_id"] == fid],
        key=lambda ci: ci["created_at"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_cabin_inventory(ci) for ci in page], limit, offset, total)


@bp.post("/irops/flights/<fid>/delay")
def delay_flight(fid):
    caller = authenticate()
    require_role(caller, ["OpsController"])
    body = get_json_body()
    # shape first
    new_dep = req_datetime(body, "new_sched_dep_utc")
    new_arr = req_datetime(body, "new_sched_arr_utc")
    expected_version = body.get("expected_flight_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_flight_version is required and must be an integer")
    event_id_raw = body.get("disruption_event_id")
    if event_id_raw is not None and not isinstance(event_id_raw, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "disruption_event_id must be a string")
    if new_arr <= new_dep:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "new_sched_arr_utc must be strictly after new_sched_dep_utc")
    # existence
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    linked_event = None
    if event_id_raw is not None:
        linked_event = db.disruption_events.get(event_id_raw)
        if linked_event is None:
            errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    # OCC before state guard
    if expected_version != f["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION,
                           "expected_flight_version does not match current flight version")
    # state guard
    if f["flight_status"] not in ("SCHEDULED", "DELAYED"):
        errors.raise_error(errors.ERR_FLIGHT_NOT_DELAYABLE,
                           "Flight cannot be delayed from state %s" % f["flight_status"])
    # linked event state verified last
    if linked_event is not None and linked_event["event_status"] not in EVENT_DELAY_STATES:
        errors.raise_error(errors.ERR_EVENT_INVALID_STATE,
                           "Linked event must be OPEN, ASSESSING, or RECOVERY")
    # mutate
    f["sched_dep_utc"] = new_dep
    f["sched_arr_utc"] = new_arr
    if linked_event is not None and f["disruption_event_id"] is None:
        f["disruption_event_id"] = linked_event["id"]
    f["flight_status"] = "DELAYED"
    touch(f)
    crew_legality_reeval(f)
    run_misconnect_cascade(f)
    return success_object(serialize_flight(f), 200)


@bp.post("/irops/flights/<fid>/cancel")
def cancel_flight(fid):
    caller = authenticate()
    require_role(caller, ["OpsController"])
    body = get_json_body()
    event_id = body.get("disruption_event_id")
    if event_id is None or not isinstance(event_id, str):
        if event_id is None:
            # missing required field
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "disruption_event_id is required")
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "disruption_event_id must be a string")
    expected_version = body.get("expected_flight_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_flight_version is required and must be an integer")
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    event = db.disruption_events.get(event_id)
    if event is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "DisruptionEvent not found")
    if expected_version != f["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION,
                           "expected_flight_version does not match current flight version")
    if f["flight_status"] not in ("SCHEDULED", "DELAYED"):
        errors.raise_error(errors.ERR_FLIGHT_NOT_CANCELLABLE,
                           "Flight cannot be cancelled from state %s" % f["flight_status"])
    if event["event_status"] not in EVENT_CANCEL_STATES:
        errors.raise_error(errors.ERR_EVENT_INVALID_STATE,
                           "Event must be ASSESSING or RECOVERY to cancel under it")
    f["flight_status"] = "CANCELLED"
    f["disruption_event_id"] = event["id"]
    from db import now
    f["cancelled_at"] = now()
    touch(f)
    run_cancel_cascade(f, event)
    return success_object(serialize_flight(f), 200)


@bp.post("/irops/flights/<fid>/depart")
def depart_flight(fid):
    caller = authenticate()
    require_role(caller, ["OpsController"])
    body = get_json_body()
    act_dep = req_datetime(body, "act_dep_utc")
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    if f["flight_status"] not in ("SCHEDULED", "DELAYED"):
        errors.raise_error(errors.ERR_FLIGHT_NOT_DELAYABLE,
                           "Flight cannot depart from state %s" % f["flight_status"])
    f["act_dep_utc"] = act_dep
    f["flight_status"] = "IN_FLIGHT"
    touch(f)
    return success_object(serialize_flight(f), 200)


@bp.post("/irops/flights/<fid>/record-actuals")
def record_actuals(fid):
    caller = authenticate()
    require_role(caller, ["OpsController"])
    body = get_json_body()
    act_arr = req_datetime(body, "act_arr_utc")
    f = db.flights.get(fid)
    if f is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Flight not found")
    if f["flight_status"] != "IN_FLIGHT":
        errors.raise_error(errors.ERR_FLIGHT_NOT_DELAYABLE,
                           "Flight must be IN_FLIGHT to record actuals")
    if f["act_dep_utc"] is not None and act_arr <= f["act_dep_utc"]:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "act_arr_utc must be strictly after act_dep_utc")
    f["act_arr_utc"] = act_arr
    f["flight_status"] = "ARRIVED"
    touch(f)
    run_record_actuals(f)
    if f["disruption_event_id"]:
        recompute_event_affected(f["disruption_event_id"])
    return success_object(serialize_flight(f), 200)
