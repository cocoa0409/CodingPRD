"""Job requisitions and their lifecycle (DRAFT/OPEN/PAUSED/FILLED/CANCELLED)."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL)
from middleware import require_role, ALL_ROLES
import services as svc
from services import new_entity, touch
from util import (req_str, opt_str, opt_bool, opt_int, check_enum,
                  respond_object, respond_list, parse_pagination, paginate)
from views import requisition_view, referral_view, campaign_view

bp = Blueprint("requisitions", __name__)

READ_ROLES = tuple(ALL_ROLES)
SUBVIEW_ROLES = ("PlatformAdmin", "TalentAdmin", "Recruiter", "HiringManager",
                 "ComplianceOfficer")


def _get_requisition(req_id):
    r = store.requisitions.get(req_id)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Job requisition not found")
    return r


def _req_action(req_id, from_states, to_state, opened_at=False, actor=None):
    req = _get_requisition(req_id)
    if req["status"] in svc.REQUISITION_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Requisition is in terminal state %s" % req["status"])
    if req["status"] not in from_states:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cannot transition requisition from %s to %s" % (req["status"], to_state))
    req["status"] = to_state
    if opened_at:
        req["opened_at"] = store.clock
    touch(req)
    return req


@bp.post("/erp/job-requisitions")
def create_requisition():
    body = request.get_json(silent=True) or {}
    req_number = req_str(body, "req_number")
    title = req_str(body, "title")
    department = req_str(body, "department")
    level = body.get("level")
    if not isinstance(level, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: level")
    referral_eligible = opt_bool(body, "referral_eligible", True)
    hard_to_fill = opt_bool(body, "hard_to_fill", False)
    openings = opt_int(body, "openings", 1)
    if openings < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "openings must be >= 1")
    check_enum(level, svc.JOB_LEVELS, "level")
    require_role("TalentAdmin")
    for r in store.requisitions.values():
        if r["req_number"] == req_number:
            raise ApiError(ERR_INVALID_REQUEST, 400, "req_number must be unique")
    req = new_entity(store.requisitions, {
        "req_number": req_number,
        "title": title,
        "department": department,
        "level": level,
        "referral_eligible": referral_eligible,
        "hard_to_fill": hard_to_fill,
        "openings": openings,
        "filled_count": 0,
        "status": "DRAFT",
        "opened_at": None,
        "filled_by_candidate_id": None,
    })
    return respond_object(requisition_view(req), status=201)


@bp.get("/erp/job-requisitions")
def list_requisitions():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.requisitions.values())
    status = request.args.get("status")
    department = request.args.get("department")
    level = request.args.get("level")
    filled_by = request.args.get("filled_by_candidate_id")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if department is not None:
        items = [r for r in items if r["department"] == department]
    if level is not None:
        items = [r for r in items if r["level"] == level]
    if filled_by is not None:
        items = [r for r in items if r["filled_by_candidate_id"] == filled_by]
    page, total = paginate(items, limit, offset)
    return respond_list([requisition_view(r) for r in page], total, limit, offset)


@bp.get("/erp/job-requisitions/<req_id>")
def get_requisition(req_id):
    require_role(*READ_ROLES)
    return respond_object(requisition_view(_get_requisition(req_id)))


@bp.post("/erp/job-requisitions/<req_id>/open")
def open_requisition(req_id):
    require_role("TalentAdmin")
    req = _req_action(req_id, ("DRAFT",), "OPEN", opened_at=True)
    return respond_object(requisition_view(req))


@bp.post("/erp/job-requisitions/<req_id>/pause")
def pause_requisition(req_id):
    require_role("TalentAdmin")
    req = _req_action(req_id, ("OPEN",), "PAUSED")
    return respond_object(requisition_view(req))


@bp.post("/erp/job-requisitions/<req_id>/resume")
def resume_requisition(req_id):
    require_role("TalentAdmin")
    req = _req_action(req_id, ("PAUSED",), "OPEN")
    return respond_object(requisition_view(req))


@bp.post("/erp/job-requisitions/<req_id>/cancel")
def cancel_requisition(req_id):
    require_role("TalentAdmin")
    req = _req_action(req_id, ("DRAFT", "OPEN", "PAUSED"), "CANCELLED")
    # DRAFT has no attached referrals; the cascade simply finds none.
    svc.not_select_cascade(req, "REQ_CANCELLED", actor=g.user_id)
    return respond_object(requisition_view(req))


@bp.get("/erp/job-requisitions/<req_id>/referrals")
def requisition_referrals(req_id):
    require_role(*SUBVIEW_ROLES)
    _get_requisition(req_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [r for r in svc.sort_by_created(store.referrals.values())
             if r["job_requisition_id"] == req_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([referral_view(r) for r in page], total, limit, offset)


@bp.get("/erp/job-requisitions/<req_id>/campaigns")
def requisition_campaigns(req_id):
    require_role(*SUBVIEW_ROLES)
    _get_requisition(req_id)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in svc.sort_by_created(store.campaigns.values())
             if c["job_requisition_id"] == req_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([campaign_view(c) for c in page], total, limit, offset)
