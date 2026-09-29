"""Storm-event endpoints."""
from flask import Blueprint, request

import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("storms", __name__)


@bp.post("/vm/storm-events")
@endpoint(["UtilityForester"])
def declare_event():
    data = V.body()
    event_code = V.as_string(data, "event_code")
    severity = V.as_integer(data, "severity_level", minimum=1, maximum=5)
    district = V.as_string(data, "affected_district")
    V.unique(store.storm_events, "event_code", event_code)

    rec = store.new_record()
    rec.update({
        "event_code": event_code,
        "severity_level": severity,
        "affected_district": district,
        "reassigned_crew_count": 0,
        "preempted_assignment_count": 0,
        "status": "DECLARED",
    })
    store.storm_events[rec["id"]] = rec
    return envelope.created(store.public(rec))


@bp.post("/vm/storm-events/<sid>/activate")
@endpoint(["UtilityForester"])
def activate_event(sid):
    event = V.find(store.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    services.require_state(event, "storm_event", ["DECLARED"])
    event["status"] = "ACTIVE"
    store.touch(event)
    return envelope.ok(store.public(event))


@bp.post("/vm/storm-events/<sid>/reassignments")
@endpoint(["ContractorPlanner"])
def reassign(sid):
    event = V.find(store.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    data = V.body()
    crew = V.body_fk(data, "crew_id", store.crews, "ERR_CREW_NOT_FOUND")
    if crew is None:
        V.require(data, "crew_id")
    expected = V.as_integer(data, "expected_crew_version")
    if expected != int(crew.get("version") or 0):
        raise ApiError("ERR_STALE_CREW_VERSION",
                       "expected_crew_version does not match the crew's version")
    if (event.get("status") != "ACTIVE" or int(event.get("severity_level") or 0) < 3
            or crew.get("home_district") != event.get("affected_district")):
        raise ApiError("ERR_STORM_NOT_ACTIVE",
                       "the storm event does not accept this reassignment")
    services.storm_reassign(event, crew)
    return envelope.created(store.public(event))


@bp.post("/vm/storm-events/<sid>/demobilize")
@endpoint(["UtilityForester"])
def demobilize(sid):
    event = V.find(store.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    services.require_state(event, "storm_event", ["ACTIVE"])
    services.storm_demobilize(event)
    return envelope.ok(store.public(event))


@bp.post("/vm/storm-events/<sid>/close")
@endpoint(["UtilityForester"])
def close_event(sid):
    event = V.find(store.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")
    services.require_state(event, "storm_event", ["DEMOBILIZING"])
    for assignment in store.crew_assignments.values():
        if (assignment.get("preempted_by_storm_event_id") == event["id"]
                and assignment.get("status") == "PREEMPTED"):
            raise ApiError("ERR_INVALID_STATE",
                           "a booking is still preempted by this event")
    event["status"] = "CLOSED"
    store.touch(event)
    return envelope.ok(store.public(event))


@bp.get("/vm/storm-events/<sid>")
@endpoint(ALL_ROLES)
def get_event(sid):
    return envelope.ok(store.public(
        V.find(store.storm_events, sid, "ERR_STORM_EVENT_NOT_FOUND")))


@bp.get("/vm/storm-events")
@endpoint(ALL_ROLES)
def list_events():
    return envelope.list_response(list(store.storm_events.values()), {
        "status": request.args.get("status"),
        "affected_district": request.args.get("affected_district"),
    })
