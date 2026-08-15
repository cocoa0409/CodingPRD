"""SurgicalCase lifecycle routes + CaseDelayEvent."""

from datetime import timedelta

from flask import Blueprint, request as flask_request

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body, req_str, req_int, opt_bool
from response import success_object, success_list, parse_pagination
from services import core
from services.core import (
    LEAD_HOURS,
    ACCESS_LEAD_MINUTES,
    ACCESS_TRAIL_MINUTES,
    PREP_BUFFER_MINUTES,
    VENDOR_CAUSES,
)

bp = Blueprint("cases", __name__)


def _get_case_or_404(case_id):
    case = db.cases.get(case_id)
    if case is None:
        raise_err("ERR_CASE_NOT_FOUND", "Case not found")
    return case


def _room_conflict(room_id: str, start, end, exclude_case_id=None) -> bool:
    """Buffered half-open overlap: two cases in the same room coexist without
    conflict only when one begins at or after the other's scheduled end plus
    the room's turnover buffer. Only SCHEDULED / IN_PROGRESS cases
    participate."""
    room = db.or_rooms.get(room_id)
    buffer = room["turnover_buffer_minutes"] if room else 0
    for other in db.cases.values():
        if other["or_room_id"] != room_id:
            continue
        if other["status"] not in {"SCHEDULED", "IN_PROGRESS"}:
            continue
        if exclude_case_id is not None and other["id"] == exclude_case_id:
            continue
        o_start = db.parse_dt(other["scheduled_start_at"])
        o_end = db.parse_dt(other["scheduled_end_at"])
        # conflict iff NOT (new_start >= existing_end + buffer OR
        # existing_start >= new_end + buffer)
        if start >= o_end + timedelta(minutes=buffer):
            continue
        if o_start >= end + timedelta(minutes=buffer):
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

@bp.post("/cases")
def create_case():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["ORScheduler"])

    case_number = req_str(body, "case_number")
    or_room_id = req_str(body, "or_room_id")
    procedure_type = req_str(body, "procedure_type")
    surgeon_name = req_str(body, "surgeon_name")
    start = db.parse_dt(body.get("scheduled_start_at"))
    end = db.parse_dt(body.get("scheduled_end_at"))
    if start is None or end is None:
        raise_err("ERR_VALIDATION", "scheduled_start_at / scheduled_end_at must be ISO 8601 datetimes")
    if start >= end:
        raise_err("ERR_VALIDATION", "scheduled_start_at must be earlier than scheduled_end_at")

    # Existence (body FK fields, declared input order): or_room_id
    if or_room_id not in db.or_rooms:
        raise_err("ERR_ROOM_NOT_FOUND", "OR room not found")

    # Uniqueness: case_number
    for c in db.cases.values():
        if c["case_number"] == case_number:
            raise_err("ERR_DUPLICATE_CASE_NUMBER", "case_number already exists")

    if _room_conflict(or_room_id, start, end):
        raise_err("ERR_ROOM_TIME_CONFLICT", "Case window collides with another case in this room")

    case = {
        "case_number": case_number,
        "or_room_id": or_room_id,
        "procedure_type": procedure_type,
        "surgeon_name": surgeon_name,
        "scheduled_start_at": db.fmt_ts(start),
        "scheduled_end_at": db.fmt_ts(end),
        "actual_start_at": None,
        "actual_end_at": None,
        "status": "SCHEDULED",
        "delay_minutes_provisional": 0,
        "vendor_delay_minutes_provisional": 0,
        "vendor_delay_minutes_final": None,
        "_start_override_used": False,
    }
    core.stamp_new(case)
    db.cases[case["id"]] = case
    return success_object(core.serialize(case), status=201)


@bp.get("/cases")
def list_cases():
    get_auth()
    or_room_id = flask_request.args.get("or_room_id")
    status = flask_request.args.get("status")
    items = sorted(db.cases.values(), key=lambda c: c["_seq"])
    if or_room_id:
        items = [c for c in items if c["or_room_id"] == or_room_id]
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(c) for c in page], limit, offset, total)


@bp.get("/cases/<id>")
def get_case(id):
    get_auth()
    case = _get_case_or_404(id)
    return success_object(core.serialize(case))


@bp.post("/cases/<id>/reschedule")
def reschedule_case(id):
    _, role = get_auth()
    body = get_body(required=True)

    start = db.parse_dt(body.get("scheduled_start_at"))
    end = db.parse_dt(body.get("scheduled_end_at"))
    if start is None or end is None:
        raise_err("ERR_VALIDATION", "scheduled_start_at / scheduled_end_at must be ISO 8601 datetimes")
    if start >= end:
        raise_err("ERR_VALIDATION", "scheduled_start_at must be earlier than scheduled_end_at")
    expected = body.get("expected_case_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err("ERR_VALIDATION", "expected_case_version is required and must be an integer")

    require_role(role, ["ORScheduler"])
    case = _get_case_or_404(id)

    # OCC
    if expected != case["version"]:
        raise_err("ERR_STALE_VERSION", "Case version mismatch")

    # State guard: reschedule is only meaningful for a case that has not started.
    if case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "Only a SCHEDULED case can be rescheduled")

    if _room_conflict(case["or_room_id"], start, end, exclude_case_id=case["id"]):
        raise_err("ERR_ROOM_TIME_CONFLICT", "Case window collides with another case in this room")

    case["scheduled_start_at"] = db.fmt_ts(start)
    case["scheduled_end_at"] = db.fmt_ts(end)

    # Re-derive deadlines for linked APPROVED requests.
    for request in core.requests_of_case(case["id"]):
        if request["status"] != "APPROVED":
            continue
        lead = LEAD_HOURS[request["priority_class"]]
        request["required_delivery_by"] = db.fmt_ts(start - timedelta(hours=lead))
        core.touch(request)
        for tray in core.trays_of_request(request["id"]):
            tray["required_sterile_ready_by"] = db.fmt_ts(start - timedelta(minutes=PREP_BUFFER_MINUTES))
            core.recompute_tray_projection(tray)
            core.touch(tray)
        core.recompute_readiness(request)

    # Recompute pass windows for REQUESTED / APPROVED passes of this case.
    for p in db.access_passes.values():
        if p["case_id"] == case["id"] and p["status"] in {"REQUESTED", "APPROVED"}:
            p["window_start_at"] = db.fmt_ts(start - timedelta(minutes=ACCESS_LEAD_MINUTES))
            p["window_end_at"] = db.fmt_ts(end + timedelta(minutes=ACCESS_TRAIL_MINUTES))
            core.touch(p)

    core.touch(case)
    return success_object(core.serialize(case))


@bp.post("/cases/<id>/start")
def start_case(id):
    _, role = get_auth()
    body = get_body()
    require_role(role, ["ORScheduler"])
    case = _get_case_or_404(id)

    override_readiness = opt_bool(body, "override_readiness", default=False)
    override_reason = body.get("override_reason")

    if case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "Only a SCHEDULED case can be started")

    # Readiness gate: every linked APPROVED request must be READY unless
    # override_readiness=true with a non-empty override_reason.
    deficient = [
        r
        for r in core.requests_of_case(case["id"])
        if r["status"] == "APPROVED" and r["readiness"] != "READY"
    ]
    if deficient:
        if not override_readiness or not (isinstance(override_reason, str) and override_reason.strip()):
            raise_err(
                "ERR_CASE_READINESS_BLOCKED",
                "A linked APPROVED request is not READY and no override was supplied",
            )

    now = db.now_dt()
    scheduled_start = db.parse_dt(case["scheduled_start_at"])
    case["actual_start_at"] = db.fmt_ts(now)
    delay = db.whole_minutes(now - scheduled_start)
    case["delay_minutes_provisional"] = delay
    case["vendor_delay_minutes_provisional"] = delay if (deficient and override_readiness) else 0
    case["status"] = "IN_PROGRESS"
    case["_start_override_used"] = bool(deficient and override_readiness)

    # STAGED trays of linked requests -> IN_USE
    for request in core.requests_of_case(case["id"]):
        for tray in core.trays_of_request(request["id"]):
            if tray["status"] == "STAGED":
                tray["status"] = "IN_USE"
                core.recompute_tray_projection(tray)
                core.touch(tray)
        core.recompute_readiness(request)

    # Override used: one OPEN escalation per non-READY APPROVED request.
    if deficient and override_readiness:
        for request in deficient:
            core.create_escalation(
                request["id"], core._readiness_flip_escalation_type(request), linked_tray_id=None
            )

    core.touch(case)
    return success_object(core.serialize(case))


@bp.post("/cases/<id>/complete")
def complete_case(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORScheduler"])
    case = _get_case_or_404(id)

    if case["status"] != "IN_PROGRESS":
        raise_err("ERR_CASE_INVALID_STATE", "Only an IN_PROGRESS case can be completed")

    now = db.now_dt()
    case["actual_end_at"] = db.fmt_ts(now)

    # Final vendor delay attribution.
    events = [e for e in db.delay_events.values() if e["case_id"] == case["id"]]
    if events:
        vendor_sum = sum(e["minutes"] for e in events if e["cause"] in VENDOR_CAUSES)
        case["vendor_delay_minutes_final"] = min(case["delay_minutes_provisional"], vendor_sum)
    else:
        case["vendor_delay_minutes_final"] = case["vendor_delay_minutes_provisional"]

    case["status"] = "COMPLETED"

    # Tray cascade.
    for request in core.requests_of_case(case["id"]):
        for tray in core.trays_of_request(request["id"]):
            s = tray["status"]
            if s == "IN_USE":
                tray["status"] = "AWAITING_PICKUP"  # IN_USE -> USED -> AWAITING_PICKUP
            elif s in {"CHECKED_IN", "PROCESSING", "STERILE_READY", "STAGED", "QUARANTINED"}:
                tray["status"] = "AWAITING_PICKUP"
            elif s in {"EXPECTED", "MISSING", "DELIVERY_PENDING"}:
                tray["status"] = "CANCELLED"
            else:
                continue
            core.recompute_tray_projection(tray)
            core.touch(tray)
        core.recompute_readiness(request)

    core.touch(case)
    return success_object(core.serialize(case))


@bp.post("/cases/<id>/cancel")
def cancel_case(id):
    _, role = get_auth()
    get_body()
    require_role(role, ["ORScheduler"])
    case = _get_case_or_404(id)

    if case["status"] != "SCHEDULED":
        raise_err("ERR_CASE_INVALID_STATE", "Only a SCHEDULED case can be cancelled")

    # Requests in DRAFT/SUBMITTED/APPROVED -> CANCELLED (with tray, penalty,
    # escalation cascade handled inside cancel_request_cascade).
    for request in core.requests_of_case(case["id"]):
        if request["status"] in {"DRAFT", "SUBMITTED", "APPROVED"}:
            core.cancel_request_cascade(request)

    # Access passes of the case: REQUESTED -> DENIED (case_cancelled);
    # APPROVED -> REVOKED.
    for p in db.access_passes.values():
        if p["case_id"] != case["id"]:
            continue
        if p["status"] == "REQUESTED":
            p["status"] = "DENIED"
            p["denial_reason"] = "case_cancelled"
            core.touch(p)
        elif p["status"] == "APPROVED":
            p["status"] = "REVOKED"
            core.touch(p)

    case["status"] = "CANCELLED"
    core.touch(case)
    return success_object(core.serialize(case))


# ---------------------------------------------------------------------------
# Delay events
# ---------------------------------------------------------------------------

@bp.post("/cases/<id>/delay-events")
def create_delay_event(id):
    user_id, role = get_auth()
    body = get_body(required=True)

    cause = body.get("cause")
    allowed_causes = VENDOR_CAUSES | {"PATIENT", "STAFFING", "OTHER"}
    if cause is None or cause not in allowed_causes:
        raise_err("ERR_DELAY_EVENT_INVALID", "cause must be a valid delay cause")
    minutes = body.get("minutes")
    if minutes is None or isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise_err("ERR_DELAY_EVENT_INVALID", "minutes must be a positive integer")

    require_role(role, ["ORScheduler", "ORCirculatorNurse"])
    case = _get_case_or_404(id)

    attributable_request_id = body.get("attributable_request_id")

    # Case must be IN_PROGRESS or COMPLETED.
    if case["status"] not in {"IN_PROGRESS", "COMPLETED"}:
        raise_err("ERR_DELAY_EVENT_INVALID", "Delay events require the case to be IN_PROGRESS or COMPLETED")

    if cause in VENDOR_CAUSES:
        if attributable_request_id is None:
            raise_err("ERR_DELAY_REQUEST_LINK", "attributable_request_id is required for vendor causes")
        if not isinstance(attributable_request_id, str):
            raise_err("ERR_DELAY_REQUEST_LINK", "attributable_request_id must be a string")
        linked = db.requests.get(attributable_request_id)
        if linked is None or linked["case_id"] != case["id"]:
            raise_err("ERR_DELAY_REQUEST_LINK", "attributable_request_id must be a request of this case")
    else:
        if attributable_request_id is not None:
            raise_err("ERR_DELAY_REQUEST_LINK", "attributable_request_id must be omitted for non-vendor causes")

    # Attribution cap: sum of vendor-cause minutes after insert must be
    # <= case.delay_minutes_provisional.
    if cause in VENDOR_CAUSES:
        existing = sum(
            e["minutes"]
            for e in db.delay_events.values()
            if e["case_id"] == case["id"] and e["cause"] in VENDOR_CAUSES
        )
        if existing + minutes > case["delay_minutes_provisional"]:
            raise_err("ERR_CASE_DELAY_OVERATTRIBUTED", "Vendor-cause delay minutes exceed total delay")

    event = {
        "case_id": case["id"],
        "cause": cause,
        "minutes": minutes,
        "attributable_request_id": attributable_request_id if cause in VENDOR_CAUSES else None,
        "recorded_by_role": role,
    }
    core.stamp_new(event, with_version=False)
    db.delay_events[event["id"]] = event
    return success_object(core.serialize(event), status=201)


@bp.get("/delay-events")
def list_delay_events():
    get_auth()
    case_id = flask_request.args.get("case_id")
    attributable_request_id = flask_request.args.get("attributable_request_id")
    items = sorted(db.delay_events.values(), key=lambda e: e["_seq"])
    if case_id:
        items = [e for e in items if e["case_id"] == case_id]
    if attributable_request_id:
        items = [e for e in items if e["attributable_request_id"] == attributable_request_id]
    total = len(items)
    limit, offset = parse_pagination(flask_request.args)
    page = items[offset : offset + limit]
    return success_list([core.serialize(e) for e in page], limit, offset, total)


@bp.get("/delay-events/<id>")
def get_delay_event(id):
    get_auth()
    event = db.delay_events.get(id)
    if event is None:
        raise_err("ERR_DELAY_EVENT_NOT_FOUND", "Delay event not found")
    return success_object(core.serialize(event))
