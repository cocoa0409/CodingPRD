"""CompPlan routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
    ERR_TENURE_INELIGIBLE, ERR_MERIT_BUDGET_EXCEEDED, ERR_EQUITY_POOL_EXCEEDED,
    ERR_PROMO_JUMP_INVALID, ERR_STALE_CYCLE_VERSION, ERR_STALE_REVIEW_VERSION,
    ERR_VALIDATION,
)
from middleware import get_caller, require_role
from response import ok_object, ok_array
from services.common import (
    init_common, touch, public, paginate, get_body, require_fields, as_int,
)
from services.comp import compute_merit, compute_equity, tenure_years, MIN_TENURE_YEARS

bp = Blueprint("comp_plans", __name__)


def plan_view(p):
    return public(p)


def _validate_promo(plan_type, promo_band_jump):
    if plan_type == "MERIT_ONLY":
        if promo_band_jump != 0:
            raise err(ERR_PROMO_JUMP_INVALID, "promo_band_jump must be 0 for MERIT_ONLY")
    elif plan_type == "MERIT_AND_PROMO":
        if promo_band_jump not in (1, 2):
            raise err(ERR_PROMO_JUMP_INVALID,
                      "promo_band_jump must be 1 or 2 for MERIT_AND_PROMO")


@bp.route("/comp-plans", methods=["POST"])
def create_plan():
    _, role = get_caller()
    require_role(role, {"Manager"})
    body = get_body()
    require_fields(body, ["cycle_id", "review_id", "plan_type", "expected_review_version"])
    cycle = db.cycles.get(body["cycle_id"])
    if not cycle:
        raise err(ERR_NOT_FOUND, "cycle_id not found")
    review = db.reviews.get(body["review_id"])
    if not review:
        raise err(ERR_NOT_FOUND, "review_id not found")
    plan_type = body["plan_type"]
    if plan_type not in ("MERIT_ONLY", "MERIT_AND_PROMO"):
        raise err(ERR_VALIDATION, "plan_type invalid")

    # state: review must be CALIBRATED
    if review["status"] != "CALIBRATED":
        raise err(ERR_INVALID_STATE, "Review must be CALIBRATED")

    promo_band_jump = body.get("promo_band_jump", 0)
    if not isinstance(promo_band_jump, int) or isinstance(promo_band_jump, bool):
        raise err(ERR_VALIDATION, "promo_band_jump must be an integer")
    # promo jump validity (priority 14)
    _validate_promo(plan_type, promo_band_jump)

    # tenure gate (priority 11)
    employee = db.employees[review["employee_id"]]
    if tenure_years(cycle, employee) < MIN_TENURE_YEARS:
        raise err(ERR_TENURE_INELIGIBLE, "Employee tenure < 1 year")

    # OCC on review version (priority 15)
    expected = body["expected_review_version"]
    if expected != review["version"]:
        raise err(ERR_STALE_REVIEW_VERSION, "Stale review version")

    merit_pct, merit_amount = compute_merit(
        cycle["id"], review, plan_type, promo_band_jump)
    equity_units = compute_equity(cycle, review)

    p = {
        "cycle_id": cycle["id"],
        "review_id": review["id"],
        "plan_type": plan_type,
        "merit_pct": merit_pct,
        "merit_amount": merit_amount,
        "promo_band_jump": promo_band_jump,
        "equity_refresh_units": equity_units,
        "status": "DRAFT",
    }
    init_common(p)
    db.comp_plans[p["id"]] = p
    return ok_object(plan_view(p), 201)


@bp.route("/comp-plans", methods=["GET"])
def list_plans():
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover", "Manager"})
    cycle_id = request.args.get("cycle_id")
    review_id = request.args.get("review_id")
    status = request.args.get("status")
    items = [
        p for p in db.comp_plans.values()
        if (cycle_id is None or p["cycle_id"] == cycle_id)
        and (review_id is None or p["review_id"] == review_id)
        and (status is None or p["status"] == status)
    ]
    page, limit, offset, total, has_more = paginate(items)
    return ok_array([plan_view(p) for p in page], limit, offset, total, has_more)


@bp.route("/comp-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = get_caller()
    require_role(role, {"HrAdmin", "HrbpPartner", "CompApprover", "Manager"})
    p = db.comp_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Comp plan not found")
    return ok_object(plan_view(p))


@bp.route("/comp-plans/<pid>/recompute", methods=["POST"])
def recompute_plan(pid):
    _, role = get_caller()
    require_role(role, {"Manager"})
    p = db.comp_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Comp plan not found")
    if p["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Plan is not DRAFT")
    body = get_body()
    plan_type = body.get("plan_type", p["plan_type"])
    if plan_type not in ("MERIT_ONLY", "MERIT_AND_PROMO"):
        raise err(ERR_VALIDATION, "plan_type invalid")
    promo_band_jump = body.get("promo_band_jump", p["promo_band_jump"])
    if not isinstance(promo_band_jump, int) or isinstance(promo_band_jump, bool):
        raise err(ERR_VALIDATION, "promo_band_jump must be an integer")
    _validate_promo(plan_type, promo_band_jump)

    cycle = db.cycles[p["cycle_id"]]
    review = db.reviews[p["review_id"]]
    employee = db.employees[review["employee_id"]]
    if tenure_years(cycle, employee) < MIN_TENURE_YEARS:
        raise err(ERR_TENURE_INELIGIBLE, "Employee tenure < 1 year")

    merit_pct, merit_amount = compute_merit(
        cycle["id"], review, plan_type, promo_band_jump)
    equity_units = compute_equity(cycle, review)
    p["plan_type"] = plan_type
    p["promo_band_jump"] = promo_band_jump
    p["merit_pct"] = merit_pct
    p["merit_amount"] = merit_amount
    p["equity_refresh_units"] = equity_units
    touch(p)
    return ok_object(plan_view(p))


@bp.route("/comp-plans/<pid>/propose", methods=["POST"])
def propose_plan(pid):
    _, role = get_caller()
    require_role(role, {"Manager"})
    p = db.comp_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Comp plan not found")
    if p["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Plan is not DRAFT")
    review = db.reviews[p["review_id"]]
    cycle = db.cycles[p["cycle_id"]]
    if review["status"] != "CALIBRATED":
        raise err(ERR_INVALID_STATE, "Review must be CALIBRATED")
    if cycle["status"] != "COMP_PLANNING":
        raise err(ERR_INVALID_STATE, "Cycle must be in COMP_PLANNING")
    p["status"] = "PROPOSED"
    touch(p)
    return ok_object(plan_view(p))


@bp.route("/comp-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    user_id, role = get_caller()
    require_role(role, {"CompApprover"})
    p = db.comp_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Comp plan not found")
    if p["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Plan is not PROPOSED")
    review = db.reviews[p["review_id"]]
    cycle = db.cycles[p["cycle_id"]]

    # segregation of duties (priority 6)
    if user_id == review["reviewer_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Approver must not be the reviewer")

    body = get_body()
    require_fields(body, ["expected_cycle_version"])

    # merit budget (priority 12)
    eligible_salary = sum(
        r["base_salary"] for r in db.reviews.values()
        if r["cycle_id"] == cycle["id"]
        and r["status"] in ("CALIBRATED", "FINALIZED")
    )
    merit_cap = cycle["merit_budget_pct"] * eligible_salary
    if cycle["merit_committed_total"] + p["merit_amount"] > merit_cap + 1e-9:
        raise err(ERR_MERIT_BUDGET_EXCEEDED, "Merit budget exceeded")

    # equity pool (priority 13)
    if cycle["equity_committed_total"] + p["equity_refresh_units"] > \
            cycle["equity_refresh_pool"] + 1e-9:
        raise err(ERR_EQUITY_POOL_EXCEEDED, "Equity pool exceeded")

    # OCC on cycle version (priority 15)
    if body["expected_cycle_version"] != cycle["version"]:
        raise err(ERR_STALE_CYCLE_VERSION, "Stale cycle version")

    # commit
    cycle["merit_committed_total"] = _round2(
        cycle["merit_committed_total"] + p["merit_amount"])
    cycle["equity_committed_total"] = _round3(
        cycle["equity_committed_total"] + p["equity_refresh_units"])
    p["status"] = "APPROVED"
    touch(p)

    # review CALIBRATED -> FINALIZED
    review["status"] = "FINALIZED"
    touch(review)

    # cure open PIP if band no longer pip_eligible
    from routes.cycles import bands_for_cycle
    band = next((b for b in bands_for_cycle(cycle["id"])
                 if b["label"] == review["final_rating"]), None)
    if band is not None and not band.get("pip_eligible"):
        for pip in db.pip_cases.values():
            if pip["review_id"] == review["id"] and pip["status"] == "OPEN":
                pip["status"] = "CURED"
                touch(pip)

    touch(cycle)
    return ok_object(plan_view(p))


@bp.route("/comp-plans/<pid>/reject", methods=["POST"])
def reject_plan(pid):
    user_id, role = get_caller()
    require_role(role, {"CompApprover"})
    p = db.comp_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Comp plan not found")
    if p["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Plan is not PROPOSED")
    review = db.reviews[p["review_id"]]
    if user_id == review["reviewer_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Rejector must not be the reviewer")
    p["status"] = "REJECTED"
    touch(p)
    return ok_object(plan_view(p))


def _round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _round3(value):
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
