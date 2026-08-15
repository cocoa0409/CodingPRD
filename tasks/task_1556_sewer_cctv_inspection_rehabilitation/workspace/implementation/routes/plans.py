"""RehabPlan endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_invalid_state, err_not_found, err_conflict, err_stale_version
from services.common import (
    body, require_string, require_enum, parse_pagination, paginate,
    get_segment, get_plan, sweep_notice_expiry, recompute_plan_provisional,
)

bp = Blueprint("plans", __name__)

READ_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead"]
METHODS = {"CIPP_LINING", "SPOT_REPAIR", "FULL_REPLACE"}


def plan_view(p):
    return {
        "id": p["id"],
        "segment_id": p["segment_id"],
        "method": p["method"],
        "basis_inspection_id": p["basis_inspection_id"],
        "status": p["status"],
        "provisional_total_cents": p["provisional_total_cents"],
        "final_total_cents": p["final_total_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/sewer/segments/<id>/rehab-plans")
def create_plan(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    segment = get_segment(id)
    payload = body()
    method = require_enum(payload, "method", METHODS)
    basis_id = require_string(payload, "basis_inspection_id")
    basis = db.inspections.get(basis_id)
    if basis is None:
        raise err_not_found("basis inspection not found")
    if basis["segment_id"] != segment["id"]:
        raise err_not_found("basis inspection not on this segment")
    ent = {
        "id": db.new_id(),
        "segment_id": segment["id"],
        "method": method,
        "basis_inspection_id": basis_id,
        "status": "DRAFT",
        "provisional_total_cents": 0,
        "final_total_cents": None,
    }
    db.stamp_new(ent)
    db.plans[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(plan_view(ent), status=201)


@bp.get("/sewer/rehab-plans/<id>")
def get_plan_route(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    p = get_plan(id)
    return success_object(plan_view(p))


@bp.get("/sewer/segments/<id>/rehab-plans")
def list_plans_for_segment(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    segment = get_segment(id)
    limit, offset = parse_pagination()
    items = [p for p in db.plans.values() if p["segment_id"] == segment["id"]]
    st = request.args.get("status")
    if st:
        items = [p for p in items if p["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([plan_view(p) for p in page], limit, offset, total)


@bp.get("/sewer/rehab-plans")
def list_plans_xseg():
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.plans.values())
    bi = request.args.get("basis_inspection_id")
    if bi:
        items = [p for p in items if p["basis_inspection_id"] == bi]
    st = request.args.get("status")
    if st:
        items = [p for p in items if p["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([plan_view(p) for p in page], limit, offset, total)


def _check_method_compatible(plan, segment, basis):
    """ERR_METHOD_INCOMPATIBLE on violation."""
    method = plan["method"]
    obs = [d for d in db.defects.values() if d["inspection_id"] == basis["id"]]
    structural = [d for d in obs if d["family"] == "STRUCTURAL"]
    if method == "SPOT_REPAIR":
        if segment["structural_grade"] > 3:
            raise err_conflict("ERR_METHOD_INCOMPATIBLE", "SPOT_REPAIR requires structural_grade <= 3")
        high = [d for d in structural if d["grade"] >= 3]
        if len(high) < 1 or len(high) > 2:
            raise err_conflict("ERR_METHOD_INCOMPATIBLE", "SPOT_REPAIR requires exactly 1-2 structural observations grade >= 3")
    elif method == "CIPP_LINING":
        if segment["structural_grade"] < 2:
            raise err_conflict("ERR_METHOD_INCOMPATIBLE", "CIPP_LINING requires structural_grade >= 2")
        if segment["material"] == "BRICK":
            raise err_conflict("ERR_METHOD_INCOMPATIBLE", "CIPP_LINING not allowed for BRICK")
    # FULL_REPLACE always allowed


@bp.post("/sewer/rehab-plans/<id>/propose")
def propose_plan(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    plan = get_plan(id)
    if plan["status"] != "DRAFT":
        raise err_invalid_state("plan not DRAFT")
    segment = db.segments[plan["segment_id"]]
    basis = db.inspections.get(plan["basis_inspection_id"])
    if basis is None or basis["status"] != "CERTIFIED":
        raise err_conflict("ERR_BASIS_NOT_CERTIFIED", "basis inspection not CERTIFIED")
    _check_method_compatible(plan, segment, basis)
    # recompute provisional (0 when no work order yet)
    recompute_plan_provisional(plan["id"])
    plan["status"] = "PROPOSED"
    db.touch(plan)
    sweep_notice_expiry()
    return success_object(plan_view(plan))


@bp.post("/sewer/rehab-plans/<id>/approve")
def approve_plan(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    plan = get_plan(id)
    if plan["status"] != "PROPOSED":
        raise err_invalid_state("plan not PROPOSED")
    segment = db.segments[plan["segment_id"]]
    # Uniqueness: no other plan in {PROPOSED, APPROVED, EXECUTING} on same segment
    for other in db.plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["segment_id"] == segment["id"] and other["status"] in ("PROPOSED", "APPROVED", "EXECUTING"):
            raise err_conflict("ERR_PLAN_CONFLICT", "segment has another active plan")
    # OCC
    payload = body()
    expected = payload.get("expected_plan_version")
    if expected is None:
        raise err_invalid_request("expected_plan_version required")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_plan_version must be integer")
    if expected != plan["version"]:
        raise err_stale_version()
    # Budget (evaluated last)
    district = db.districts[segment["district_id"]]
    new_total = district["budget_committed_cents"] + plan["provisional_total_cents"]
    if new_total > district["budget_cents"]:
        raise err_conflict("ERR_BUDGET_EXCEEDED", "approval would exceed district budget")
    district["budget_committed_cents"] = new_total
    db.touch(district)
    segment["rehab_status"] = "PLANNED"
    db.touch(segment)
    plan["status"] = "APPROVED"
    db.touch(plan)
    sweep_notice_expiry()
    return success_object(plan_view(plan))


@bp.post("/sewer/rehab-plans/<id>/reopen")
def reopen_plan(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    plan = get_plan(id)
    if plan["status"] != "APPROVED":
        raise err_invalid_state("plan not APPROVED")
    segment = db.segments[plan["segment_id"]]
    # no child WO progressed beyond ISSUED
    for wo in db.work_orders.values():
        if wo["plan_id"] == plan["id"] and wo["execution_status"] not in ("ISSUED", "CANCELLED"):
            raise err_conflict("ERR_WORK_STARTED", "a child work order has progressed past ISSUED")
    district = db.districts[segment["district_id"]]
    district["budget_committed_cents"] = max(0, district["budget_committed_cents"] - plan["provisional_total_cents"])
    db.touch(district)
    # segment.rehab_status := NONE if no other APPROVED/EXECUTING plan
    still_active = False
    for other in db.plans.values():
        if other["id"] == plan["id"]:
            continue
        if other["segment_id"] == segment["id"] and other["status"] in ("APPROVED", "EXECUTING"):
            still_active = True
            break
    if not still_active:
        segment["rehab_status"] = "NONE"
        db.touch(segment)
    plan["status"] = "DRAFT"
    db.touch(plan)
    sweep_notice_expiry()
    return success_object(plan_view(plan))


@bp.post("/sewer/rehab-plans/<id>/cancel")
def cancel_plan(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    plan = get_plan(id)
    if plan["status"] not in ("DRAFT", "PROPOSED"):
        raise err_invalid_state("plan not DRAFT/PROPOSED")
    plan["status"] = "CANCELLED"
    db.touch(plan)
    sweep_notice_expiry()
    return success_object(plan_view(plan))
