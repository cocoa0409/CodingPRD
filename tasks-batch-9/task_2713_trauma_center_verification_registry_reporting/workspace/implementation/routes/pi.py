"""The performance improvement and patient safety loop: events, corrective
actions, loop closure and the compensating reopen (PRD 3.7)."""
from flask import Blueprint

import calc
import cascade
import serializers as ser
from auth import identity, require_roles, require_scope
from common import days, new_record, sorted_records
from envelope import respond_list, respond_object, touch
from errors import ApiError
from store import clock_now, db
from validate import (
    check_enum,
    filter_eq,
    get_body,
    opt_str,
    paginate,
    req_dt,
    req_str,
)

bp = Blueprint("pi", __name__)

EVENT_TYPES = (
    "UNDER_TRIAGE",
    "DELAYED_SURGEON",
    "DEFICIENCY_ESCALATION",
    "MORTALITY_REVIEW",
    "TRANSFER_DELAY",
)
SEVERITIES = ("HIGH", "MEDIUM", "LOW")
ACTION_TYPES = ("EDUCATION", "PROTOCOL_CHANGE", "CREDENTIAL_ACTION", "EQUIPMENT")
PI_READ_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "TraumaMedicalDirector",
    "VerificationReviewer",
    "StateDesignationOfficer",
]
ACTION_READ_ROLES = [
    "SystemAdmin",
    "TraumaProgramManager",
    "TraumaMedicalDirector",
    "VerificationReviewer",
]


def load_event(event_id):
    event = db.pi_events.get(event_id)
    if event is None:
        raise ApiError("ERR_PI_EVENT_NOT_FOUND")
    return event


def load_action(action_id):
    action = db.actions.get(action_id)
    if action is None:
        raise ApiError("ERR_REFERENCED_RESOURCE_NOT_FOUND")
    return action


@bp.route("/pi-events", methods=["POST"])
def create_event():
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    body = get_body()
    center_id = req_str(body, "center_id")
    center = db.centers.get(center_id)
    if center is None:
        raise ApiError("ERR_CENTER_NOT_FOUND")
    case_id = opt_str(body, "case_id")
    if case_id is not None and case_id not in db.cases:
        raise ApiError("ERR_CASE_NOT_FOUND")
    event_type = req_str(body, "event_type")
    severity = req_str(body, "severity")
    source_deficiency_id = opt_str(body, "source_deficiency_id")
    check_enum(event_type, EVENT_TYPES)
    check_enum(severity, SEVERITIES)
    record = cascade.create_pi_event(
        center,
        event_type,
        severity,
        case_id=case_id,
        source_deficiency_id=source_deficiency_id,
        due_days=calc.LOOP_CLOSURE_DAYS,
        origin="MANUAL",
    )
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.pi_event(record), 201)


@bp.route("/pi-events/<event_id>", methods=["GET"])
def read_event(event_id):
    user_id, role = identity()
    require_roles(role, PI_READ_ROLES)
    event = load_event(event_id)
    return respond_object(lambda: ser.pi_event(event))


@bp.route("/pi-events", methods=["GET"])
def list_events():
    user_id, role = identity()
    require_roles(role, PI_READ_ROLES)
    records = sorted_records(list(db.pi_events.values()))
    for field in ("center_id", "case_id", "source_deficiency_id", "status", "event_type", "origin"):
        records = filter_eq(records, field)
    page, meta = paginate(records)
    return respond_list(lambda: [ser.pi_event(r) for r in page], meta)


@bp.route("/pi-events/<event_id>/start-review", methods=["POST"])
def start_review(event_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    event = load_event(event_id)
    if event["status"] not in ("IDENTIFIED", "REOPENED"):
        raise ApiError("ERR_INVALID_PI_STATE")
    event["status"] = "UNDER_REVIEW"
    return respond_object(lambda: ser.pi_event(event))


@bp.route("/pi-events/<event_id>/corrective-actions", methods=["POST"])
def attach_action(event_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector", "TraumaProgramManager"])
    event = load_event(event_id)
    require_scope(user_id, role, event["center_id"])
    body = get_body()
    action_type = req_str(body, "action_type")
    owner_user_id = req_str(body, "owner_user_id")
    due_at = req_dt(body, "due_at")
    check_enum(action_type, ACTION_TYPES)
    if event["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_PI_STATE")
    record = new_record()
    record.update(
        {
            "pi_event_id": event_id,
            "action_type": action_type,
            "owner_user_id": owner_user_id,
            "due_at": due_at,
            "completion_status": "OPEN",
            "completed_at": None,
            "verified_at": None,
            "verified_by_user_id": None,
            "completion_note": None,
        }
    )
    db.actions[record["id"]] = record
    event["status"] = "ACTION_PLANNED"
    cascade.refresh_event_action_counts(event)
    touch(event)
    return respond_object(lambda: ser.action(record), 201)


@bp.route("/pi-events/<event_id>/corrective-actions", methods=["GET"])
def list_actions(event_id):
    user_id, role = identity()
    require_roles(role, ACTION_READ_ROLES)
    event = load_event(event_id)
    records = calc.actions_of_event(event_id)
    records = filter_eq(records, "completion_status")
    page, meta = paginate(records)
    return respond_list(lambda: [ser.action(r) for r in page], meta)


@bp.route("/corrective-actions/<action_id>/complete", methods=["POST"])
def complete_action(action_id):
    user_id, role = identity()
    require_roles(role, ["TraumaProgramManager", "TraumaMedicalDirector"])
    action = load_action(action_id)
    event = db.pi_events.get(action["pi_event_id"])
    require_scope(user_id, role, event["center_id"] if event else None)
    body = get_body()
    note = opt_str(body, "completion_note")
    # Band E order: the PI event's state is checked before the action's own state
    if event is None or event["status"] not in ("ACTION_PLANNED", "REOPENED"):
        raise ApiError("ERR_INVALID_PI_STATE")
    if action["completion_status"] != "OPEN":
        raise ApiError("ERR_INVALID_ACTION_STATE")
    action["completion_status"] = "COMPLETED"
    action["completed_at"] = clock_now()
    if note is not None:
        action["completion_note"] = note
    return respond_object(lambda: ser.action(action))


@bp.route("/corrective-actions/<action_id>/verify", methods=["POST"])
def verify_action(action_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector", "VerificationReviewer"])
    action = load_action(action_id)
    if action["completion_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_ACTION_STATE")
    if user_id == action["owner_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    action["completion_status"] = "VERIFIED"
    action["verified_at"] = clock_now()
    action["verified_by_user_id"] = user_id
    event = db.pi_events.get(action["pi_event_id"])
    if event is not None:
        cascade.refresh_event_action_counts(event)
        touch(event)
    return respond_object(lambda: ser.action(action))


@bp.route("/pi-events/<event_id>/close-loop", methods=["POST"])
def close_loop(event_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector"])
    event = load_event(event_id)
    body = get_body()
    note = req_str(body, "loop_closure_note")
    if event["status"] != "ACTION_PLANNED":
        raise ApiError("ERR_INVALID_PI_STATE")
    actions = calc.actions_of_event(event_id)
    if not actions or any(a["completion_status"] != "VERIFIED" for a in actions):
        raise ApiError("ERR_OPEN_ACTIONS_BLOCK_LOOP_CLOSURE")
    if any(a["owner_user_id"] == user_id for a in actions):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    event["status"] = "LOOP_CLOSED"
    event["closed_at"] = clock_now()
    event["loop_closure_note"] = note
    cascade.refresh_event_action_counts(event)
    center = db.centers.get(event["center_id"])
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.pi_event(event))


@bp.route("/pi-events/<event_id>/reopen", methods=["POST"])
def reopen_event(event_id):
    user_id, role = identity()
    require_roles(role, ["TraumaMedicalDirector", "VerificationReviewer"])
    event = load_event(event_id)
    body = get_body()
    reason = req_str(body, "reopen_reason")
    if event["status"] != "LOOP_CLOSED":
        raise ApiError("ERR_INVALID_PI_STATE")
    now = clock_now()
    event["status"] = "REOPENED"
    event["closed_at"] = None
    event["review_round"] = event["review_round"] + 1
    event["loop_closure_due_at"] = now + days(calc.ESCALATION_REMEDIATION_DAYS)
    event["reopen_reason"] = reason
    for action in calc.actions_of_event(event_id):
        if action["completion_status"] == "VERIFIED":
            action["completion_status"] = "OPEN"
            action["completed_at"] = None
            action["verified_at"] = None
            action["verified_by_user_id"] = None
    cascade.refresh_event_action_counts(event)
    center = db.centers.get(event["center_id"])
    cascade.cascade_center(center, cycles=True)
    return respond_object(lambda: ser.pi_event(event))
