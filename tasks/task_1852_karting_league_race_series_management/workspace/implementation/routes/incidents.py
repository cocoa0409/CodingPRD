"""Incident reports, steward adjudication (segregation of duties), and appeals."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_SELF_ADJUDICATION,
    ERR_NOT_ENTRY_DRIVER,
    ERR_APPEAL_LIMIT,
)
from middleware import authorized, ANY_ROLE
from response import success_object, success_array, success_list
from services import core
from services.cascades import (
    apply_time_penalty,
    reverse_time_penalty,
    disqualify_entry,
)
from validate import json_body, v_id, v_str, v_enum, is_int

bp = Blueprint("incidents", __name__)

DECISIONS = {"UPHELD", "DISMISSED"}
PENALTY_KINDS = {"NONE", "TIME_SECONDS", "DISQUALIFICATION"}


@bp.post("/events/<event_id>/incidents")
def create_incident(event_id):
    caller = authorized(["RaceDirector", "Steward"])
    body = json_body()
    entry_id = v_id(body, "entry_id")
    session_id = v_id(body, "session_id")
    description = v_str(body, "description")
    event = core.must_find("events", event_id, "event not found")
    entry = core.find("entries", entry_id)
    if entry is None or entry["event_id"] != event["id"]:
        raise_error(ERR_NOT_FOUND, "entry not found in this event")
    session = core.find("sessions", session_id)
    if session is None or session["event_id"] != event["id"]:
        raise_error(ERR_NOT_FOUND, "session not found in this event")
    incident = core.create_record("incidents", {
        "event_id": event["id"],
        "entry_id": entry["id"],
        "session_id": session["id"],
        "description": description,
        "reporter_user_id": caller.user_id,
        "status": "REPORTED",
        "penalty_kind": None,
        "penalty_seconds": None,
        "adjudicator_user_id": None,
        "appeal_count": 0,
        # internal bookkeeping for the DISMISSED-after-appeal compensation
        "_applied_penalty": None,
    })
    return success_object(core.serialize_incident(incident), 201)


@bp.get("/events/<event_id>/incidents")
def list_event_incidents(event_id):
    authorized(ANY_ROLE)
    event = core.must_find("events", event_id, "event not found")
    items = [i for i in core.db["incidents"].values() if i["event_id"] == event["id"]]
    return success_array([core.serialize_incident(i) for i in core.list_sorted(items)])


@bp.get("/incidents/<incident_id>")
def get_incident(incident_id):
    authorized(ANY_ROLE)
    incident = core.must_find("incidents", incident_id, "incident not found")
    return success_object(core.serialize_incident(incident))


@bp.get("/incidents")
def list_incidents():
    authorized(ANY_ROLE)
    entry_id = request.args.get("entry_id")
    session_id = request.args.get("session_id")
    items = list(core.db["incidents"].values())
    if entry_id is not None:
        items = [i for i in items if i["entry_id"] == entry_id]
    if session_id is not None:
        items = [i for i in items if i["session_id"] == session_id]
    items = core.list_sorted(items)
    page, total, limit, offset = core.paginate(items)
    return success_list([core.serialize_incident(i) for i in page], total, limit, offset)


@bp.post("/incidents/<incident_id>/open-review")
def open_review(incident_id):
    authorized(["Steward"])
    incident = core.must_find("incidents", incident_id, "incident not found")
    if incident["status"] not in ("REPORTED", "APPEALED"):
        raise_error(ERR_INVALID_STATE, "incident is not REPORTED or APPEALED")
    incident["status"] = "UNDER_REVIEW"
    core.touch(incident)
    return success_object(core.serialize_incident(incident))


@bp.post("/incidents/<incident_id>/adjudicate")
def adjudicate(incident_id):
    caller = authorized(["Steward"])
    incident = core.find("incidents", incident_id)
    # priority 2: segregation of duties — adjudicator must not be the reporter
    if incident is not None and caller.user_id == incident["reporter_user_id"]:
        raise_error(ERR_SELF_ADJUDICATION, "the adjudicating steward reported this incident")
    body = json_body()
    # priority 3: body well-formedness
    decision = v_enum(body, "decision", DECISIONS)
    penalty_kind = body.get("penalty_kind")
    if penalty_kind is not None and penalty_kind not in PENALTY_KINDS:
        raise_error(ERR_INVALID_REQUEST, "penalty_kind must be one of NONE, TIME_SECONDS, DISQUALIFICATION")
    penalty_seconds = body.get("penalty_seconds")
    if penalty_kind == "TIME_SECONDS":
        if not is_int(penalty_seconds) or penalty_seconds <= 0:
            raise_error(ERR_INVALID_REQUEST, "penalty_seconds is required and must be > 0 when penalty_kind is TIME_SECONDS")
    elif penalty_seconds is not None:
        raise_error(ERR_INVALID_REQUEST, "penalty_seconds must be null unless penalty_kind is TIME_SECONDS")
    # priority 4: existence
    if incident is None:
        raise_error(ERR_NOT_FOUND, "incident not found")
    # priority 6: state machine + upheld-ruling gates
    if incident["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "incident is not UNDER_REVIEW")
    if decision == "UPHELD":
        kind = penalty_kind or "NONE"
        if kind == "TIME_SECONDS":
            session = core.db["sessions"].get(incident["session_id"])
            event = core.db["events"].get(incident["event_id"])
            if session is None or session["status"] != "SCORED":
                raise_error(ERR_INVALID_STATE, "TIME_SECONDS requires the incident session to be SCORED")
            if event is None or event["status"] not in ("IN_PROGRESS", "COMPLETED"):
                raise_error(ERR_INVALID_STATE, "TIME_SECONDS requires the event to be IN_PROGRESS or COMPLETED")
        elif kind == "DISQUALIFICATION":
            entry = core.db["entries"].get(incident["entry_id"])
            if entry is None or entry["status"] not in ("TECH_CHECK", "TECH_PASSED", "GRID_LOCKED"):
                raise_error(ERR_INVALID_STATE, "DISQUALIFICATION requires the entry in TECH_CHECK, TECH_PASSED, or GRID_LOCKED")

    # apply
    incident["adjudicator_user_id"] = caller.user_id
    if decision == "UPHELD":
        kind = penalty_kind or "NONE"
        incident["status"] = "UPHELD"
        incident["penalty_kind"] = kind
        incident["penalty_seconds"] = penalty_seconds if kind == "TIME_SECONDS" else None
        if kind == "TIME_SECONDS":
            apply_time_penalty(incident, penalty_seconds)
            incident["_applied_penalty"] = {"seconds": penalty_seconds}
        elif kind == "DISQUALIFICATION":
            entry = core.db["entries"].get(incident["entry_id"])
            if entry is not None:
                disqualify_entry(entry)
            incident["_applied_penalty"] = None
        else:
            incident["_applied_penalty"] = None
    else:  # DISMISSED
        incident["status"] = "DISMISSED"
        incident["penalty_kind"] = None
        incident["penalty_seconds"] = None
        applied = incident.get("_applied_penalty")
        if applied:
            # compensation on re-adjudication after appeal: reverse the penalty
            reverse_time_penalty(incident, applied["seconds"])
            incident["_applied_penalty"] = None
    core.touch(incident)
    return success_object(core.serialize_incident(incident))


@bp.post("/incidents/<incident_id>/appeal")
def appeal(incident_id):
    caller = authorized(["Driver"])
    incident = core.find("incidents", incident_id)
    # priority 2: only the incident entry's driver may appeal
    if incident is not None:
        entry = core.db["entries"].get(incident["entry_id"])
        owner = entry["driver_id"] if entry else None
        if caller.user_id != owner:
            raise_error(ERR_NOT_ENTRY_DRIVER, "only the incident entry's driver may appeal")
    if incident is None:
        raise_error(ERR_NOT_FOUND, "incident not found")
    if incident["status"] != "UPHELD":
        raise_error(ERR_INVALID_STATE, "incident is not UPHELD")
    if incident["appeal_count"] >= 1:
        raise_error(ERR_APPEAL_LIMIT, "appeal limit reached for this incident")
    incident["status"] = "APPEALED"
    incident["appeal_count"] += 1
    core.touch(incident)
    return success_object(core.serialize_incident(incident))
