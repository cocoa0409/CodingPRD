"""Requisition endpoints."""

from flask import Blueprint, request

import db
from errors import (
    raise_err, ERR_REQUISITION_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_REQUISITION_INVALID_STATE, ERR_STALE_REQUISITION_VERSION,
    ERR_SALARY_RANGE_INVALID, ERR_UNAUTHORIZED_ROLE, ERR_INVALID_REQUEST,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_string,
    req_enum, req_int, get_pagination, paginate,
)
from response import success
from services import calc
from services import offer_ops

bp = Blueprint("requisitions", __name__)

ROLE_LEVELS = ["L3", "L4", "L5", "L6", "L7"]
GEO_TIERS = ["T1", "T2", "T3"]
READ_ROLES = ["HiringManager", "Recruiter", "CompAnalyst", "FinanceController",
              "DepartmentDirector", "VPPeople", "HRAdmin"]


def serialize(req):
    return req


def _validate_range(budget, mn, mid, mx, headcount):
    if not (0 < mn < mid <= mx) or budget <= 0 or headcount < 1:
        raise_err(ERR_SALARY_RANGE_INVALID,
                  "Salary range, budget, or headcount constraint violated")


def _get_req(req_id):
    req = db.requisitions.get(req_id)
    if req is None:
        raise_err(ERR_REQUISITION_NOT_FOUND, "Requisition not found")
    return req


def _require_owner(req, uid):
    if req["hiring_manager_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Not the owning hiring manager")


@bp.route("/api/requisitions", methods=["POST"])
def create():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["title", "department", "role_level", "geo_tier",
                     "annual_budget_cents", "salary_min_cents",
                     "salary_mid_cents", "salary_max_cents", "headcount_authorized"],
                    [])
    title = req_string(body, "title")
    department = req_string(body, "department")
    role_level = req_enum(body, "role_level", ROLE_LEVELS)
    geo_tier = req_enum(body, "geo_tier", GEO_TIERS)
    budget = req_int(body, "annual_budget_cents")
    mn = req_int(body, "salary_min_cents")
    mid = req_int(body, "salary_mid_cents")
    mx = req_int(body, "salary_max_cents")
    headcount = req_int(body, "headcount_authorized")
    require_role(role, ["HiringManager"])
    _validate_range(budget, mn, mid, mx, headcount)
    ts = db.now_ms()
    req = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "title": title,
        "department": department,
        "role_level": role_level,
        "geo_tier": geo_tier,
        "hiring_manager_id": uid,
        "annual_budget_cents": budget,
        "salary_min_cents": mn,
        "salary_mid_cents": mid,
        "salary_max_cents": mx,
        "headcount_authorized": headcount,
        "headcount_filled": 0,
        "committed_budget_cents": 0,
        "status": "DRAFT",
        "close_reason": None,
    }
    db.requisitions[req["id"]] = req
    return success(serialize(req), status=201)


@bp.route("/api/requisitions", methods=["GET"])
def list_all():
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    hm_f = request.args.get("hiring_manager_id")
    items = sorted(db.requisitions.values(), key=lambda r: r["created_at"])
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    if hm_f is not None:
        items = [r for r in items if r["hiring_manager_id"] == hm_f]
    page, pg = paginate(items, limit, offset)
    return success([serialize(r) for r in page], response_type="array", pagination=pg)


@bp.route("/api/requisitions/<req_id>", methods=["GET"])
def get_one(req_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    req = _get_req(req_id)
    return success(serialize(req))


@bp.route("/api/requisitions/<req_id>", methods=["PATCH"])
def patch(req_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body,
                    ["expected_requisition_version"],
                    ["title", "department", "annual_budget_cents",
                     "salary_min_cents", "salary_mid_cents", "salary_max_cents",
                     "headcount_authorized"])
    expected = req_int(body, "expected_requisition_version")
    require_role(role, ["HiringManager"])
    req = _get_req(req_id)
    _require_owner(req, uid)
    if req["status"] != "DRAFT":
        raise_err(ERR_REQUISITION_INVALID_STATE, "Requisition is not in DRAFT")
    if expected != req["version"]:
        raise_err(ERR_STALE_REQUISITION_VERSION, "Stale requisition version")

    new = dict(req)
    for f in ["title", "department"]:
        if f in body:
            new[f] = req_string(body, f)
    for f in ["annual_budget_cents", "salary_min_cents", "salary_mid_cents",
              "salary_max_cents", "headcount_authorized"]:
        if f in body:
            new[f] = req_int(body, f)
    _validate_range(new["annual_budget_cents"], new["salary_min_cents"],
                    new["salary_mid_cents"], new["salary_max_cents"],
                    new["headcount_authorized"])
    for f in ["title", "department", "annual_budget_cents", "salary_min_cents",
              "salary_mid_cents", "salary_max_cents", "headcount_authorized"]:
        req[f] = new[f]
    calc.touch(req)
    return success(serialize(req))


@bp.route("/api/requisitions/<req_id>/submit", methods=["POST"])
def submit(req_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["HiringManager"])
    req = _get_req(req_id)
    _require_owner(req, uid)
    if req["status"] != "DRAFT":
        raise_err(ERR_REQUISITION_INVALID_STATE, "Submit only from DRAFT")
    req["status"] = "BUDGET_REVIEW"
    calc.touch(req)
    return success(serialize(req))


@bp.route("/api/requisitions/<req_id>/review-decision", methods=["POST"])
def review_decision(req_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["decision"], ["note"])
    decision = req_enum(body, "decision", ["APPROVE", "RETURN"])
    require_role(role, ["FinanceController", "CompAnalyst"])
    req = _get_req(req_id)
    if req["status"] not in ("BUDGET_REVIEW", "RANGE_APPROVAL"):
        raise_err(ERR_REQUISITION_INVALID_STATE,
                  "Review decision only at BUDGET_REVIEW or RANGE_APPROVAL")
    # Stage-dependent role check (priority 3)
    if req["status"] == "BUDGET_REVIEW" and role != "FinanceController":
        raise_err(ERR_UNAUTHORIZED_ROLE, "BUDGET_REVIEW stage requires FinanceController")
    if req["status"] == "RANGE_APPROVAL" and role != "CompAnalyst":
        raise_err(ERR_UNAUTHORIZED_ROLE, "RANGE_APPROVAL stage requires CompAnalyst")
    if decision == "APPROVE":
        req["status"] = "RANGE_APPROVAL" if req["status"] == "BUDGET_REVIEW" else "OPEN"
    else:
        req["status"] = "DRAFT"
    calc.touch(req)
    return success(serialize(req))


@bp.route("/api/requisitions/<req_id>/hold", methods=["POST"])
def hold(req_id):
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["action"], [])
    action = req_enum(body, "action", ["PAUSE", "RESUME"])
    require_role(role, ["HiringManager"])
    req = _get_req(req_id)
    _require_owner(req, uid)
    if action == "PAUSE":
        if req["status"] != "OPEN":
            raise_err(ERR_REQUISITION_INVALID_STATE, "PAUSE only from OPEN")
        req["status"] = "PAUSED"
    else:
        if req["status"] != "PAUSED":
            raise_err(ERR_REQUISITION_INVALID_STATE, "RESUME only from PAUSED")
        req["status"] = "OPEN"
    calc.touch(req)
    return success(serialize(req))


@bp.route("/api/requisitions/<req_id>/cancel", methods=["POST"])
def cancel(req_id):
    uid, role = get_actor()
    body = get_json_body() if db.request_has_body() else {}
    if body:
        validate_fields(body, [], ["reason"])
    require_role(role, ["HiringManager"])
    req = _get_req(req_id)
    _require_owner(req, uid)
    if req["status"] not in ("OPEN", "PAUSED"):
        raise_err(ERR_REQUISITION_INVALID_STATE, "Cancel only from OPEN or PAUSED")
    req["status"] = "CANCELLED"
    calc.touch(req)
    offer_ops.requisition_cascade(req, "REQUISITION_CANCELLED")
    return success(serialize(req))
