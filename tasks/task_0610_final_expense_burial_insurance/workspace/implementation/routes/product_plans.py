"""ProductPlan endpoints (PRD §3.1)."""
from flask import Blueprint

import db
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles
from response import success

bp = Blueprint("product_plans", __name__)

BENEFIT_TYPES = {"GUARANTEED_ISSUE", "GRADED_BENEFIT", "LEVEL_BENEFIT"}

DEFAULTS = {
    "min_issue_age": 45,
    "max_issue_age": 85,
    "graded_period_months": 24,
    "contestability_period_months": 24,
    "graded_refund_apr": 0.10,
    "base_monthly_rate_per_1000_cents": 400,
    "cash_value_factor_per_1000_cents": 1500,
    "cash_value_vesting_years": 3,
    "max_loan_to_cash_value_pct": 0.90,
    "loan_apr": 0.08,
    "loan_cooldown_days": 30,
    "grace_period_days": 31,
    "reinstatement_window_days": 180,
}


@bp.route("/product-plans", methods=["POST"])
def create_plan():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin"})
    body = get_body()
    require_fields(body, ["name", "benefit_type", "face_tiers", "age_bands", "surrender_charge_tiers"])
    if body["benefit_type"] not in BENEFIT_TYPES:
        raise err("ERR_VALIDATION", "Invalid benefit_type")
    for arr in ("face_tiers", "age_bands", "surrender_charge_tiers"):
        if not isinstance(body[arr], list):
            raise err("ERR_VALIDATION", "%s must be an array" % arr)

    plan = {
        "name": body["name"],
        "benefit_type": body["benefit_type"],
        "face_tiers": body["face_tiers"],
        "age_bands": body["age_bands"],
        "surrender_charge_tiers": body["surrender_charge_tiers"],
    }
    for key, default in DEFAULTS.items():
        plan[key] = body.get(key, default) if body.get(key) is not None else default

    with db.LOCK:
        db.stamp_full(plan)
        db.product_plans[plan["id"]] = plan
    return success(serialize(plan), status=201, response_type="object")


@bp.route("/product-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Underwriter", "ClaimsExaminer", "Policyholder"})
    plan = db.product_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "ProductPlan not found")
    return success(serialize(plan), status=200, response_type="object")


@bp.route("/product-plans", methods=["GET"])
def list_plans():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Underwriter", "ClaimsExaminer", "Policyholder"})
    from flask import request
    items = list(db.product_plans.values())
    benefit_type = request.args.get("benefit_type")
    if benefit_type:
        items = [p for p in items if p["benefit_type"] == benefit_type]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(p) for p in page], status=200, response_type="array", pagination=meta)
