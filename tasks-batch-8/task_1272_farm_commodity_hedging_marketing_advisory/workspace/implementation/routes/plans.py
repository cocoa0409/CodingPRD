"""MarketingPlan endpoints."""

from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, req_body, require_fields, req_number,
    pagination_params, page_slice, get_or_404, touch,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_plan
from services import (
    compute_coverage_cap, recompute_plan_counters, governing_agreement,
)


bp = Blueprint("plans", __name__)


@bp.route("/advisory/marketing-plans", methods=["POST"])
def create_plan():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["operation_id", "baseline_id", "max_priced_pct"])
    operation_id = body["operation_id"]
    baseline_id = body["baseline_id"]
    if not isinstance(operation_id, str) or not isinstance(baseline_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id and baseline_id must be strings", 400)
    max_priced = req_number(body, "max_priced_pct")
    if max_priced < D("0.05") or max_priced > D("1.00"):
        raise ApiError("ERR_VALIDATION", "max_priced_pct must be in 0.05..1.00", 400)

    op = DB.operations.get(operation_id)
    if op is None:
        raise ApiError("ERR_NOT_FOUND", f"GrowerOperation not found: {operation_id}", 404)
    baseline = DB.baselines.get(baseline_id)
    if baseline is None:
        raise ApiError("ERR_NOT_FOUND", f"ProductionBaseline not found: {baseline_id}", 404)
    if baseline["operation_id"] != operation_id:
        raise ApiError("ERR_VALIDATION", "baseline_id does not belong to operation_id", 400)

    pid = db.new_id()
    now = db.now_iso()
    plan = {
        "id": pid,
        "operation_id": operation_id,
        "baseline_id": baseline_id,
        "max_priced_pct": max_priced,
        "expected_bushels_snapshot": None,
        "committed_contract_bushels": 0,
        "uncommitted_bushels": 0,
        "hedged_bushels": 0,
        "priced_contract_bushels": 0,
        "coverage_cap_bushels": 0,
        "pending_recommendation_count": 0,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.plans[pid] = plan
    return success_object(ser_plan(plan), status=201)


@bp.route("/advisory/marketing-plans/<planId>", methods=["GET"])
def get_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    check_grower_ownership(user_id, role, p["operation_id"])
    return success_object(ser_plan(p))


@bp.route("/advisory/marketing-plans", methods=["GET"])
def list_plans():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower", "ComplianceOfficer"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    baseline_id = request.args.get("baseline_id")
    status = request.args.get("status")
    items = list(DB.plans.values())
    if role == "Grower":
        items = [p for p in items if p["operation_id"] == user_id]
    if operation_id is not None:
        items = [p for p in items if p["operation_id"] == operation_id]
    if baseline_id is not None:
        items = [p for p in items if p["baseline_id"] == baseline_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    slice_, total = page_slice(items, limit, offset)
    return success_list([ser_plan(p) for p in slice_], limit, offset, total)


@bp.route("/advisory/marketing-plans/<planId>", methods=["PUT"])
def amend_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    body = req_body()
    require_fields(body, ["expected_marketing_plan_version"])
    emv = body.get("expected_marketing_plan_version")
    if isinstance(emv, bool) or not isinstance(emv, int):
        raise ApiError("ERR_VALIDATION", "expected_marketing_plan_version must be an integer", 400)
    max_priced = None
    if "max_priced_pct" in body and body["max_priced_pct"] is not None:
        max_priced = req_number(body, "max_priced_pct")
        if max_priced < D("0.05") or max_priced > D("1.00"):
            raise ApiError("ERR_VALIDATION", "max_priced_pct must be in 0.05..1.00", 400)
    # OCC
    if emv != p["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_marketing_plan_version does not match the plan's current version", 412)
    # State gate: amendment allowed while DRAFT or ACTIVE
    if p["status"] not in {"DRAFT", "ACTIVE"}:
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {p['status']} cannot be amended", 409)
    if max_priced is not None:
        p["max_priced_pct"] = max_priced
    if p["status"] == "ACTIVE":
        op = DB.operations[p["operation_id"]]
        p["coverage_cap_bushels"] = compute_coverage_cap(p, op)
    touch(p)
    return success_object(ser_plan(p))


def _check_agreement_current(op_id):
    """Compliance gates for activation/resume. Returns governing agreement."""
    agreement = governing_agreement(op_id)
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Operation lacks an ACTIVE AdvisoryAgreement", 409)
    ds = agreement["disclosure_status"]
    if ds in {"REQUIRED", "DELIVERED", "NONE"}:
        raise ApiError("ERR_DISCLOSURE_NOT_ACKNOWLEDGED", "Disclosure not ACKNOWLEDGED", 409)
    if ds == "STALE":
        raise ApiError("ERR_DISCLOSURE_STALE", "Disclosure acknowledgment is stale", 409)
    # ACKNOWLEDGED: check version pinning
    if agreement.get("acknowledged_agreement_version") != agreement["version"]:
        raise ApiError("ERR_DISCLOSURE_STALE", "Disclosure acknowledgment version is stale", 409)
    return agreement


@bp.route("/advisory/marketing-plans/<planId>/activate", methods=["POST"])
def activate_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    if p["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {p['status']} cannot be activated", 409)
    # compliance gates
    _check_agreement_current(p["operation_id"])
    # referential state
    baseline = DB.baselines.get(p["baseline_id"])
    if baseline is None or baseline["status"] != "CERTIFIED":
        raise ApiError("ERR_BASELINE_NOT_CERTIFIED", "Referenced baseline is not CERTIFIED", 409)
    op = DB.operations[p["operation_id"]]
    p["expected_bushels_snapshot"] = baseline["expected_bushels"]
    p["status"] = "ACTIVE"
    p["coverage_cap_bushels"] = compute_coverage_cap(p, op)
    # One request = one mutation on the plan (PRD 2.4 / 3.3: a request that
    # recomputes derived counters still increments version by exactly one).
    # recompute_plan_counters performs the single touch.
    recompute_plan_counters(p)
    return success_object(ser_plan(p))


@bp.route("/advisory/marketing-plans/<planId>/suspend", methods=["POST"])
def suspend_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "ComplianceOfficer"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {p['status']} cannot be suspended", 409)
    p["status"] = "SUSPENDED"
    touch(p)
    return success_object(ser_plan(p))


@bp.route("/advisory/marketing-plans/<planId>/resume", methods=["POST"])
def resume_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    if p["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {p['status']} cannot be resumed", 409)
    _check_agreement_current(p["operation_id"])
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(ser_plan(p))


@bp.route("/advisory/marketing-plans/<planId>/close", methods=["POST"])
def close_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    p = get_or_404(DB.plans, planId, "MarketingPlan")
    if p["status"] not in {"ACTIVE", "SUSPENDED"}:
        raise ApiError("ERR_INVALID_STATE", f"Plan in state {p['status']} cannot be closed", 409)
    # No OPEN/PARTIALLY_DELIVERED contract, no OPEN position
    for c in DB.contracts.values():
        if c["plan_id"] == p["id"] and c["fulfillment_status"] in {"OPEN", "PARTIALLY_DELIVERED"}:
            raise ApiError("ERR_INVALID_STATE", "Plan has open contracts", 409)
    for pos in DB.positions.values():
        if pos.get("plan_id") == p["id"] and pos["status"] == "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Plan has open positions", 409)
    _do_close_plan(p)
    return success_object(ser_plan(p))


def _do_close_plan(p):
    p["status"] = "CLOSED"
    touch(p)
    # Cancel remaining PENDING targets
    for t in DB.price_targets.values():
        if t["plan_id"] == p["id"] and t["status"] == "PENDING":
            t["status"] = "CANCELLED"
            touch(t)
