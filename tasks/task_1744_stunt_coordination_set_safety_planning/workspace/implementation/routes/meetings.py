"""SafetyMeeting: schedule (with signoff fan-out), start, complete, adjourn."""

from flask import Blueprint, request

from db import store
from domain import (
    get_production,
    get_sequence,
    get_meeting,
    gate_posture_active,
    facility_conflict,
    meeting_signoffs,
    serialize_meeting,
    stamp_new,
    stamp_mutable,
    touch,
    BASE_SIGNOFF_DEPARTMENTS,
    default_sort_key,
)
from errors import (
    err,
    ERR_SEQUENCE_INVALID_STATE,
    ERR_MEETING_INVALID_STATE,
    ERR_SIGNOFFS_PENDING,
    ERR_FACILITY_BUFFER_CONFLICT,
    ERR_INVALID_TIME_RANGE,
    ERR_CROSS_PRODUCTION_REFERENCE,
)
from middleware import (
    auth,
    require_role,
    get_body,
    validate_payload,
    pagination_params,
    v_string,
    v_datetime,
)
from response import ok, ok_list
from util import new_id

bp = Blueprint("meetings", __name__)

READ_ROLES = ["ProductionExecutive", "StuntCoordinator", "SafetyOfficer",
              "DepartmentHead", "Performer", "EquipmentInspector"]
SAFETY = ["SafetyOfficer"]


@bp.post("/api/safety-meetings")
def create_meeting():
    body = get_body()
    data = validate_payload(
        body,
        {
            "production_id": (v_string, True, None),
            "sequence_id": (v_string, True, None),
            "facility": (v_string, True, None),
            "scheduled_start": (v_datetime, True, None),
            "scheduled_end": (v_datetime, True, None),
        },
    )
    _, role = auth()
    require_role(role, ["StuntCoordinator"])

    get_production(data["production_id"])
    seq = get_sequence(data["sequence_id"])

    prod = get_production(seq["production_id"])
    gate_posture_active(prod)

    if seq["status"] not in ("DESIGN_LOCKED", "READY"):
        raise err(ERR_SEQUENCE_INVALID_STATE,
                  "Safety meetings require the sequence in DESIGN_LOCKED or READY", 409)

    if not data["scheduled_end"] > data["scheduled_start"]:
        raise err(ERR_INVALID_TIME_RANGE,
                  "scheduled_end must be after scheduled_start", 422)
    if facility_conflict(
        data["production_id"], data["facility"],
        data["scheduled_start"], data["scheduled_end"],
    ):
        raise err(ERR_FACILITY_BUFFER_CONFLICT,
                  "The facility has a meeting within the 30-minute buffered exclusion "
                  "window", 409)

    if seq["production_id"] != data["production_id"]:
        raise err(ERR_CROSS_PRODUCTION_REFERENCE,
                  "production_id must equal the sequence's production", 422)

    meeting = stamp_mutable(
        stamp_new(
            {
                "id": new_id(),
                "production_id": data["production_id"],
                "sequence_id": seq["id"],
                "facility": data["facility"],
                "scheduled_start": data["scheduled_start"],
                "scheduled_end": data["scheduled_end"],
                "status": "SCHEDULED",
                "design_revision": seq["design_revision"],
                "chair_user_id": None,
            }
        )
    )
    store.meetings[meeting["id"]] = meeting

    # fan out one PENDING DepartmentSignoff per required department
    departments = sorted(BASE_SIGNOFF_DEPARTMENTS)
    if seq["medic_standby_required"]:
        departments.append("MEDIC")
    if seq["hazard_class"] in ("FIRE", "PYRO"):
        departments.append("FIRE_SAFETY")
    for dept in sorted(departments):
        signoff = stamp_mutable(
            stamp_new(
                {
                    "id": new_id(),
                    "meeting_id": meeting["id"],
                    "department": dept,
                    "status": "PENDING",
                    "signer_user_id": None,
                    "conditions": None,
                    "refusal_reason": None,
                    "decided_at": None,
                }
            )
        )
        store.signoffs[signoff["id"]] = signoff

    return ok(serialize_meeting(meeting), 201)


@bp.get("/api/safety-meetings")
def list_meetings():
    _, role = auth()
    require_role(role, READ_ROLES)
    limit, offset = pagination_params()
    production_id = request.args.get("production_id")
    sequence_id = request.args.get("sequence_id")
    status = request.args.get("status")
    items = []
    for m in store.meetings.values():
        if production_id is not None and m["production_id"] != production_id:
            continue
        if sequence_id is not None and m["sequence_id"] != sequence_id:
            continue
        if status is not None and m["status"] != status:
            continue
        items.append(m)
    items.sort(key=default_sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([serialize_meeting(m) for m in page], total, limit, offset)


@bp.get("/api/safety-meetings/<mid>")
def get_one_meeting(mid):
    _, role = auth()
    require_role(role, READ_ROLES)
    meeting = get_meeting(mid)
    return ok(serialize_meeting(meeting), 200)


@bp.post("/api/safety-meetings/<mid>/start")
def start_meeting(mid):
    body = get_body()
    validate_payload(body, {})
    user_id, role = auth()
    require_role(role, SAFETY)
    meeting = get_meeting(mid)
    prod = get_production(meeting["production_id"])
    gate_posture_active(prod)
    if meeting["status"] != "SCHEDULED":
        raise err(ERR_MEETING_INVALID_STATE, "start requires status SCHEDULED", 409)
    meeting["status"] = "IN_SESSION"
    meeting["chair_user_id"] = user_id
    touch(meeting)
    return ok(serialize_meeting(meeting), 200)


@bp.post("/api/safety-meetings/<mid>/complete")
def complete_meeting(mid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, SAFETY)
    meeting = get_meeting(mid)
    prod = get_production(meeting["production_id"])
    gate_posture_active(prod)
    if meeting["status"] != "IN_SESSION":
        raise err(ERR_MEETING_INVALID_STATE, "complete requires status IN_SESSION", 409)
    pending = any(s["status"] == "PENDING" for s in meeting_signoffs(meeting["id"]))
    if pending:
        raise err(ERR_SIGNOFFS_PENDING,
                  "At least one department signoff is still PENDING", 409)
    meeting["status"] = "COMPLETED"
    touch(meeting)
    return ok(serialize_meeting(meeting), 200)


@bp.post("/api/safety-meetings/<mid>/adjourn")
def adjourn_meeting(mid):
    body = get_body()
    validate_payload(body, {})
    _, role = auth()
    require_role(role, SAFETY)
    meeting = get_meeting(mid)
    prod = get_production(meeting["production_id"])
    gate_posture_active(prod)
    if meeting["status"] not in ("SCHEDULED", "IN_SESSION"):
        raise err(ERR_MEETING_INVALID_STATE,
                  "adjourn requires status SCHEDULED or IN_SESSION", 409)
    meeting["status"] = "ADJOURNED"
    touch(meeting)
    return ok(serialize_meeting(meeting), 200)
