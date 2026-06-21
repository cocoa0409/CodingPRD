"""JobRequisition endpoints + state transitions."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (
    get_json_or_400,
    require_str,
    require_int,
    require_enum,
    new_id,
    now_iso,
    parse_pagination,
    paginate,
    get_or_404,
    fk_or_404,
    stamp_update,
)
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_BUDGET_EXCEEDED,
    ERR_PRECONDITION_FAILED,
    ERR_STALE_VERSION,
)
from response import success_object, success_array
from serializers import ser_requisition
from services.department import compute_committed_offer_cents
from services.cascades import (
    OFFER_NON_TERMINAL_OR_ACCEPTED,
    APPLICATION_NON_TERMINAL,
    revoke_offer_cascade,
)


bp = Blueprint("requisitions", __name__)

TARGET_LEVELS = {"JUNIOR", "MID", "SENIOR", "STAFF"}
REQUISITION_STATUSES = {"DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "CLOSED", "CANCELLED"}


@bp.post("/ats/requisitions")
def create_requisition():
    require_role({"Recruiter"})
    body = get_json_or_400()
    department_id = require_str(body, "department_id")
    title = require_str(body, "title")
    target_level = require_enum(body, "target_level", TARGET_LEVELS)
    base_min = require_int(body, "base_salary_min_cents", minimum=0)
    base_max = require_int(body, "base_salary_max_cents", minimum=0)
    openings = require_int(body, "openings", minimum=1)
    if base_max <= base_min:
        raise ApiError(ERR_INVALID_REQUEST, 400, "base_salary_max_cents must exceed base_salary_min_cents")

    # FK existence check on department.
    fk_or_404(db.departments, department_id, "department")

    req = {
        "id": new_id(),
        "department_id": department_id,
        "title": title,
        "target_level": target_level,
        "base_salary_min_cents": base_min,
        "base_salary_max_cents": base_max,
        "status": "DRAFT",
        "submitter_user_id": None,
        "approver_user_id": None,
        "approved_at": None,
        "openings": openings,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.requisitions[req["id"]] = req
    return success_object(ser_requisition(req), status=201)


@bp.get("/ats/requisitions/<req_id>")
def read_requisition(req_id):
    require_role({"PlatformAdmin", "HiringManager", "Recruiter"})
    req = get_or_404(db.requisitions, req_id, "requisition")
    return success_object(ser_requisition(req), status=200)


@bp.get("/ats/requisitions")
def list_requisitions():
    require_role({"PlatformAdmin", "HiringManager", "Recruiter"})
    limit, offset = parse_pagination()
    dept_filter = request.args.get("department_id")
    status_filter = request.args.get("status")
    rows = list(db.requisitions.values())
    if dept_filter:
        rows = [r for r in rows if r["department_id"] == dept_filter]
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return success_array([ser_requisition(r) for r in page], limit, offset, total, status=200)


@bp.post("/ats/requisitions/<req_id>/submit")
def submit_requisition(req_id):
    uid, _ = require_role({"Recruiter"})
    req = get_or_404(db.requisitions, req_id, "requisition")
    if req["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "requisition not in DRAFT")
    # PRD precondition: openings >= 1 and base_max > base_min (already enforced at create).
    if req["openings"] < 1 or req["base_salary_max_cents"] <= req["base_salary_min_cents"]:
        raise ApiError(ERR_PRECONDITION_FAILED, 409, "invalid requisition state for submit")
    req["status"] = "PENDING_APPROVAL"
    req["submitter_user_id"] = uid
    stamp_update(req)
    return success_object(ser_requisition(req), status=200)


@bp.post("/ats/requisitions/<req_id>/approve")
def approve_requisition(req_id):
    uid, _ = require_role({"HiringManager"})
    req = get_or_404(db.requisitions, req_id, "requisition")
    if req["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "requisition not in PENDING_APPROVAL")
    if uid == req.get("submitter_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "approver must differ from submitter")
    # Budget headroom check.
    dept = db.departments[req["department_id"]]
    committed = compute_committed_offer_cents(dept["id"])
    headroom = dept["hiring_budget_cents"] - committed
    required = req["openings"] * req["base_salary_max_cents"]
    if headroom < required:
        raise ApiError(ERR_BUDGET_EXCEEDED, 422, "insufficient budget headroom")
    req["status"] = "APPROVED"
    req["approver_user_id"] = uid
    req["approved_at"] = now_iso()
    stamp_update(req)
    return success_object(ser_requisition(req), status=200)


@bp.post("/ats/requisitions/<req_id>/reject")
def reject_requisition(req_id):
    uid, _ = require_role({"HiringManager"})
    req = get_or_404(db.requisitions, req_id, "requisition")
    if req["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_STATE, 409, "requisition not in PENDING_APPROVAL")
    if uid == req.get("submitter_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "approver must differ from submitter")
    req["status"] = "REJECTED"
    req["approver_user_id"] = uid
    stamp_update(req)
    return success_object(ser_requisition(req), status=200)


@bp.post("/ats/requisitions/<req_id>/cancel")
def cancel_requisition(req_id):
    require_role({"HiringManager"})
    req = get_or_404(db.requisitions, req_id, "requisition")
    body = get_json_or_400()
    expected_version = body.get("expected_requisition_version")

    if req["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "requisition not in APPROVED")

    # Precondition: no offer on this requisition is ACCEPTED.
    for off in db.offers.values():
        app = db.applications.get(off["application_id"])
        if app and app["requisition_id"] == req["id"] and off["status"] == "ACCEPTED":
            raise ApiError(ERR_PRECONDITION_FAILED, 409, "requisition has accepted offer")

    # OCC.
    if expected_version is None or not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_requisition_version required")
    if expected_version != req["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_requisition_version mismatch")

    # Cascade: applications -> WITHDRAWN, offers -> REVOKED (with downstream).
    # Withdraw all non-terminal applications on this requisition.
    for app in list(db.applications.values()):
        if app["requisition_id"] != req["id"]:
            continue
        if app["status"] in APPLICATION_NON_TERMINAL:
            app["status"] = "WITHDRAWN"
            stamp_update(app)
    # Revoke all non-terminal offers on this requisition.
    for off in list(db.offers.values()):
        a = db.applications.get(off["application_id"])
        if not a or a["requisition_id"] != req["id"]:
            continue
        if off["status"] in {"PENDING_APPROVAL", "APPROVED", "EXTENDED"}:
            revoke_offer_cascade(off)

    req["status"] = "CANCELLED"
    stamp_update(req)
    return success_object(ser_requisition(req), status=200)
