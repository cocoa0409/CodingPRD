"""DepartmentSignoff: list/get, sign, refuse."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_meeting,
    get_signoff,
    gate_posture_active,
    serialize_signoff,
    touch,
)
from errors import (
    err,
    ERR_MEETING_INVALID_STATE,
    ERR_SIGNOFF_ALREADY_DECIDED,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_nonempty_string,
)
from response import ok, ok_list

bp = Blueprint("signoffs", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
DEPT_HEAD = ["DepartmentHead"]


@bp.get("/api/department-signoffs")
def list_signoffs():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    meeting_id = request.args.get("meeting_id")
    department = request.args.get("department")
    status = request.args.get("status")
    items = []
    for s in store.signoffs.values():
        if meeting_id is not None and s["meeting_id"] != meeting_id:
            continue
        if department is not None and s["department"] != department:
            continue
        if status is not None and s["status"] != status:
            continue
        items.append(s)
    # created_at ASC, department ASC tie-break (PRD 2.3 exception)
    items.sort(key=lambda s: (s["created_at"], s["department"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_signoff(s) for s in page], total, limit, offset)


@bp.get("/api/department-signoffs/<sid>")
def get_one_signoff(sid):
    _, role = auth()
    require_role(role, READ_ROLES)
    signoff = get_signoff(sid)
    return ok(serialize_signoff(signoff), 200)


def _decision_prechecks(signoff, user_id):
    meeting = get_meeting(signoff["meeting_id"])
    prod = get_production(meeting["production_id"])
    gate_posture_active(prod)
    if signoff["status"] != "PENDING":
        raise err(ERR_SIGNOFF_ALREADY_DECIDED,
                  "The signoff has already been decided", 409)
    if meeting["status"] != "IN_SESSION":
        raise err(ERR_MEETING_INVALID_STATE,
                  "Signoffs may be decided only while the meeting is IN_SESSION", 409)
    seq = get_sequence(meeting["sequence_id"])
    if user_id == seq["coordinator_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The sequence's coordinator may not decide its department "
                  "signoffs", 403)
    return meeting


@bp.post("/api/department-signoffs/<sid>/sign")
def sign_signoff(sid):
    body = get_body()
    data = validate_payload(body, {"conditions": (v_string, False, None)})
    user_id, role = auth()
    require_role(role, DEPT_HEAD)
    signoff = get_signoff(sid)
    _decision_prechecks(signoff, user_id)

    conditions = data["conditions"]
    if conditions:
        signoff["status"] = "SIGNED_WITH_CONDITIONS"
        signoff["conditions"] = conditions
    else:
        signoff["status"] = "SIGNED"
    signoff["signer_user_id"] = user_id
    signoff["decided_at"] = store.now()
    touch(signoff)
    return ok(serialize_signoff(signoff), 200)


@bp.post("/api/department-signoffs/<sid>/refuse")
def refuse_signoff(sid):
    body = get_body()
    data = validate_payload(body, {"reason": (v_nonempty_string, True, None)})
    user_id, role = auth()
    require_role(role, DEPT_HEAD)
    signoff = get_signoff(sid)
    _decision_prechecks(signoff, user_id)

    signoff["status"] = "REFUSED"
    signoff["refusal_reason"] = data["reason"]
    signoff["signer_user_id"] = user_id
    signoff["decided_at"] = store.now()
    touch(signoff)
    return ok(serialize_signoff(signoff), 200)
