"""InsurancePolicy endpoints."""

import math
from flask import Blueprint, request

import db
from db import DB
from errors import ApiError
from helpers import (
    D, r2, to_float, req_body, require_fields, req_int, req_number,
    pagination_params, page_slice, get_or_404, touch,
)
from middleware import get_auth, require_role, check_grower_ownership
from response import success_object, success_list
from serializers import ser_policy
from services import evaluate_over_sold


bp = Blueprint("insurance", __name__)


@bp.route("/advisory/insurance-policies", methods=["POST"])
def create_policy():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor"])
    body = req_body()
    require_fields(body, ["operation_id", "baseline_id", "coverage_level_pct", "projected_price"])
    operation_id = body["operation_id"]
    baseline_id = body["baseline_id"]
    if not isinstance(operation_id, str) or not isinstance(baseline_id, str):
        raise ApiError("ERR_VALIDATION", "operation_id and baseline_id must be strings", 400)

    coverage = req_number(body, "coverage_level_pct")
    # 0.50..0.85 step 0.05
    if coverage < D("0.50") or coverage > D("0.85"):
        raise ApiError("ERR_VALIDATION", "coverage_level_pct must be in 0.50..0.85", 400)
    # step check: (coverage - 0.50) must be multiple of 0.05
    delta = (coverage - D("0.50")) / D("0.05")
    if delta != delta.to_integral_value():
        raise ApiError("ERR_VALIDATION", "coverage_level_pct must step in 0.05", 400)

    projected = req_number(body, "projected_price", positive=True)

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
    policy = {
        "id": pid,
        "operation_id": operation_id,
        "baseline_id": baseline_id,
        "coverage_level_pct": coverage,
        "projected_price": projected,
        "guarantee_bushels": None,
        "actual_harvested_bushels": None,
        "harvest_price": None,
        "indemnity_dollars": None,
        "status": "QUOTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.policies[pid] = policy
    return success_object(ser_policy(policy), status=201)


@bp.route("/advisory/insurance-policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    p = get_or_404(DB.policies, policyId, "InsurancePolicy")
    check_grower_ownership(user_id, role, p["operation_id"])
    return success_object(ser_policy(p))


@bp.route("/advisory/insurance-policies", methods=["GET"])
def list_policies():
    user_id, role = get_auth()
    require_role(role, ["CommodityAdvisor", "Grower"])
    limit, offset = pagination_params()
    operation_id = request.args.get("operation_id")
    baseline_id = request.args.get("baseline_id")
    status = request.args.get("status")
    items = list(DB.policies.values())
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
    return success_list([ser_policy(p) for p in slice_], limit, offset, total)


@bp.route("/advisory/insurance-policies/<policyId>/bind", methods=["POST"])
def bind_policy(policyId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    p = get_or_404(DB.policies, policyId, "InsurancePolicy")
    check_grower_ownership(user_id, role, p["operation_id"])
    if p["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", f"Policy in state {p['status']} cannot be bound", 409)
    baseline = DB.baselines.get(p["baseline_id"])
    if baseline is None or baseline["status"] != "CERTIFIED":
        raise ApiError("ERR_BASELINE_NOT_CERTIFIED", "Referenced baseline is not CERTIFIED", 409)
    p["guarantee_bushels"] = int(
        (D(baseline["expected_bushels"]) * D(p["coverage_level_pct"])).to_integral_value(rounding="ROUND_FLOOR")
    )
    p["status"] = "BOUND"
    touch(p)
    return success_object(ser_policy(p))


@bp.route("/advisory/insurance-policies/<policyId>/file-claim", methods=["POST"])
def file_claim(policyId):
    user_id, role = get_auth()
    require_role(role, ["Grower"])
    p = get_or_404(DB.policies, policyId, "InsurancePolicy")
    check_grower_ownership(user_id, role, p["operation_id"])
    body = req_body()
    require_fields(body, ["actual_harvested_bushels", "harvest_price"])
    actual = req_int(body, "actual_harvested_bushels", minimum=0)
    harvest = req_number(body, "harvest_price", positive=True)
    if p["status"] != "BOUND":
        raise ApiError("ERR_INVALID_STATE", f"Policy in state {p['status']} cannot file a claim", 409)
    shortfall = max(0, (p["guarantee_bushels"] or 0) - actual)
    indemnity = r2(D(shortfall) * max(D(p["projected_price"]), harvest))
    p["actual_harvested_bushels"] = actual
    p["harvest_price"] = harvest
    p["indemnity_dollars"] = indemnity
    p["status"] = "CLAIM_SETTLED"
    touch(p)
    evaluate_over_sold(p["operation_id"])
    return success_object(ser_policy(p))
