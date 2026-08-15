"""Validation protocol endpoints: the IQ/OQ/PQ pipeline (PRD section 3.3)."""
from flask import Blueprint, request

from auth import QUALITY_ENGINEER, QUALITY_MANAGER, context, require_role
from domain import list_data, serialize
from envelope import pagination_params, success
from errors import ApiError, err_sod, err_state
from store import DB, bump, new_entity, now
from timeutil import add_months
from validate import get_body, get_or_404, req_dt, req_str

bp = Blueprint("protocols", __name__)

# statuses that occupy a manufacturing line for changeover-buffer purposes
_OCCUPYING = (
    "DRAFT", "IQ_EXECUTION", "IQ_REVIEW", "OQ_EXECUTION", "OQ_REVIEW",
    "PQ_EXECUTION", "PQ_REVIEW",
)

_EXECUTION_TO_REVIEW = {
    "IQ_EXECUTION": "IQ_REVIEW",
    "OQ_EXECUTION": "OQ_REVIEW",
    "PQ_EXECUTION": "PQ_REVIEW",
}

_REVIEW_INFO = {
    "IQ_REVIEW": ("iq", "OQ_EXECUTION"),
    "OQ_REVIEW": ("oq", "PQ_EXECUTION"),
    "PQ_REVIEW": ("pq", "VALIDATED"),
}


@bp.post("/api/validation-protocols")
def create_protocol():
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    data = get_body()
    protocol_code = req_str(data, "protocol_code")
    dmr_id = req_str(data, "dmr_id")
    line_id = req_str(data, "line_id")
    planned_start = req_dt(data, "planned_start")
    planned_end = req_dt(data, "planned_end")
    if not planned_start < planned_end:
        from errors import err_validation
        raise err_validation("planned_start must be strictly before planned_end")
    # step 4: body FK existence
    dmr = get_or_404("dmrs", dmr_id)
    line = get_or_404("lines", line_id)
    # step 10: line changeover-buffer conflict vs occupying protocols
    buffer = line["changeover_buffer_hours"]
    for p in DB["protocols"].values():
        if p["line_id"] != line_id or p["status"] not in _OCCUPYING:
            continue
        if planned_start >= p["planned_end"]:
            gap_hours = (planned_start - p["planned_end"]).total_seconds() / 3600.0
        elif p["planned_start"] >= planned_end:
            gap_hours = (p["planned_start"] - planned_end).total_seconds() / 3600.0
        else:
            gap_hours = -1.0  # overlapping windows
        if gap_hours < buffer:
            raise ApiError("ERR_LINE_WINDOW_CONFLICT", 409,
                           "Planned window violates the line's changeover buffer versus an occupying protocol")
    # step 11: pinned DMR must be APPROVED at creation
    if dmr["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "Protocol creation requires the DMR revision in APPROVED")
    # step 12
    if any(p["protocol_code"] == protocol_code for p in DB["protocols"].values()):
        raise ApiError("ERR_DUPLICATE_CODE", 409, "protocol_code already exists")
    protocol = new_entity({
        "protocol_code": protocol_code,
        "dmr_id": dmr_id,
        "line_id": line_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "status": "DRAFT",
        "iq_executor_user_id": None,
        "iq_approver_user_id": None,
        "oq_executor_user_id": None,
        "oq_approver_user_id": None,
        "pq_executor_user_id": None,
        "pq_approver_user_id": None,
        "validated_at": None,
        "revalidation_due_at": None,
        "revalidation_reason": "NONE",
        "generation": 1,
    })
    DB["protocols"][protocol["id"]] = protocol
    return success(serialize(protocol), 201)


@bp.get("/api/validation-protocols")
def list_protocols():
    context()
    filters = [(n, request.args.get(n)) for n in ("dmr_id", "line_id", "status")]
    items = list_data("protocols", filters)
    limit, offset = pagination_params()
    page = items[offset:offset + limit]
    return success([serialize(o) for o in page], 200, pagination={
        "limit": limit, "offset": offset, "total_count": len(items),
        "has_more": offset + len(page) < len(items),
    })


@bp.get("/api/validation-protocols/<id>")
def get_protocol(id):
    context()
    return success(serialize(get_or_404("protocols", id)), 200)


@bp.post("/api/validation-protocols/<id>/execute-phase")
def execute_phase(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    protocol = get_or_404("protocols", id)
    if protocol["status"] not in ("DRAFT", "REVALIDATION_REQUIRED"):
        raise err_state()
    # step 9: pinned DMR must be APPROVED at this moment
    dmr = DB["dmrs"].get(protocol["dmr_id"])
    if dmr is None or dmr["status"] != "APPROVED":
        raise ApiError("ERR_DMR_NOT_APPROVED", 409,
                       "Phase execution requires the pinned DMR revision in APPROVED")
    if protocol["status"] == "REVALIDATION_REQUIRED":
        # a new validation cycle starts
        protocol["generation"] += 1
        for f in ("iq_executor_user_id", "iq_approver_user_id",
                  "oq_executor_user_id", "oq_approver_user_id",
                  "pq_executor_user_id", "pq_approver_user_id"):
            protocol[f] = None
        protocol["revalidation_reason"] = "NONE"
    protocol["status"] = "IQ_EXECUTION"
    bump(protocol)
    return success(serialize(protocol), 200)


@bp.post("/api/validation-protocols/<id>/submit-phase-review")
def submit_phase_review(id):
    uid, role = context()
    require_role(role, QUALITY_ENGINEER)
    protocol = get_or_404("protocols", id)
    target = _EXECUTION_TO_REVIEW.get(protocol["status"])
    if target is None:
        raise err_state()
    phase = protocol["status"].split("_")[0].lower()  # iq / oq / pq
    protocol[phase + "_executor_user_id"] = uid
    protocol["status"] = target
    bump(protocol)
    return success(serialize(protocol), 200)


@bp.post("/api/validation-protocols/<id>/approve-phase")
def approve_phase(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    protocol = get_or_404("protocols", id)
    info = _REVIEW_INFO.get(protocol["status"])
    # step 6: segregation of duties - approver must not be the phase's executor
    if info is not None and uid == protocol[info[0] + "_executor_user_id"]:
        raise err_sod()
    if info is None:
        raise err_state()
    phase, next_status = info
    protocol[phase + "_approver_user_id"] = uid
    protocol["status"] = next_status
    if next_status == "VALIDATED":
        protocol["validated_at"] = now()
        protocol["revalidation_due_at"] = add_months(now(), 36)
        protocol["revalidation_reason"] = "NONE"
    bump(protocol)
    return success(serialize(protocol), 200)


@bp.post("/api/validation-protocols/<id>/reject-phase")
def reject_phase(id):
    uid, role = context()
    require_role(role, QUALITY_MANAGER)
    protocol = get_or_404("protocols", id)
    info = _REVIEW_INFO.get(protocol["status"])
    if info is None:
        raise err_state()
    phase = info[0]
    protocol[phase + "_executor_user_id"] = None  # rework by any QualityEngineer
    protocol["status"] = phase.upper() + "_EXECUTION"
    bump(protocol)
    return success(serialize(protocol), 200)
