"""Compensation plan design, pay variables and the approval fork (PRD 3.3)."""
from flask import Blueprint, g

import serializers
from db import create, db, touch
from errors import ApiError, bad_request
from middleware import ALL_ROLES, endpoint
from response import created, ok, paginated
from routes.common import filters, gate, get_or_404, listing, matches
from services import audit
from validators import Body, raw_body

bp = Blueprint("plans", __name__)

PERMISSIBLE_TYPES = (
    "LOAN_VOLUME_UNITS",
    "LOAN_VOLUME_DOLLARS",
    "PERCENTAGE_OF_LOAN_AMOUNT",
    "HOURS_WORKED",
    "FILE_QUALITY_SCORE",
    "EXISTING_BORROWER_FLAG",
)
PROHIBITED_TYPES = (
    "INTEREST_RATE",
    "APR",
    "LOAN_TERM_MONTHS",
    "LTV_RATIO",
    "CREDIT_SCORE",
    "PRODUCT_TYPE",
    "PREPAYMENT_PENALTY_FLAG",
    "LOAN_PROFITABILITY",
)
VARIABLE_TYPES = PERMISSIBLE_TYPES + PROHIBITED_TYPES
DECISIONS = ("APPROVE", "REJECT")
REQUIRED_WEIGHT_TOTAL = 100
MAX_BASE_BPS = 275


def variables_of(plan_id):
    rows = [v for v in db.compensation_variables.values()
            if v["compensation_plan_id"] == plan_id]
    return rows


def recount_prohibited(plan):
    count = len([v for v in variables_of(plan["id"])
                 if v["permissibility"] == "PROHIBITED"])
    plan["prohibited_variable_count"] = count
    return count


@bp.route("/compensation-plans", methods=["POST"])
@endpoint("CompensationDesigner")
def draft_plan():
    body = Body(raw_body())
    plan_name = body.string("plan_name", min_len=1, max_len=80)
    base_basis_points = body.integer("base_basis_points", minimum=0, maximum=MAX_BASE_BPS)
    min_fee_cents = body.integer("min_fee_cents", minimum=0)
    max_fee_cents = body.integer("max_fee_cents", minimum=0)
    salary_cents_per_period = body.integer("salary_cents_per_period", required=False,
                                           default=0, minimum=0)
    volume_tier_enabled = body.boolean("volume_tier_enabled", required=False, default=False)
    concession_absorption_enabled = body.boolean("concession_absorption_enabled",
                                                 required=False, default=False)
    if max_fee_cents < min_fee_cents:
        raise bad_request("max_fee_cents must be greater than or equal to min_fee_cents.")
    row = create(db.compensation_plans, {
        "plan_name": plan_name,
        "drafted_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "base_basis_points": base_basis_points,
        "min_fee_cents": min_fee_cents,
        "max_fee_cents": max_fee_cents,
        # Recorded for examination only: it never enters per-loan commission.
        "salary_cents_per_period": salary_cents_per_period,
        "volume_tier_enabled": volume_tier_enabled,
        "concession_absorption_enabled": concession_absorption_enabled,
        "status": "DRAFT",
        "prohibited_variable_count": 0,
        "assignment_effective_from": None,
        "assignment_effective_to": None,
        "assigned_originator_id": None,
    })
    return created(serializers.compensation_plan(row))


@bp.route("/compensation-plans", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_plans():
    active = filters("status", "assigned_originator_id")
    rows = listing(db.compensation_plans, lambda r: matches(r, active))
    return paginated(rows, serializers.compensation_plan)


@bp.route("/compensation-plans/<row_id>", methods=["GET"])
@endpoint(*ALL_ROLES)
def get_plan(row_id):
    row = get_or_404(db.compensation_plans, row_id)
    return ok(serializers.compensation_plan(row))


@bp.route("/compensation-plans/<row_id>/variables", methods=["POST"])
@endpoint("CompensationDesigner")
def declare_variable(row_id):
    plan = get_or_404(db.compensation_plans, row_id)
    body = Body(raw_body())
    variable_type = body.enum("variable_type", VARIABLE_TYPES)
    weight_pct = body.integer("weight_pct", minimum=0, maximum=100)
    justification_text = body.string("justification_text", min_len=20, max_len=1000)
    gate("CompensationPlan", plan, ("DRAFT",))

    # The system, not the designer, decides permissibility.
    permissibility = "PROHIBITED" if variable_type in PROHIBITED_TYPES else "PERMISSIBLE"
    row = create(db.compensation_variables, {
        "compensation_plan_id": plan["id"],
        "variable_type": variable_type,
        "permissibility": permissibility,
        "weight_pct": weight_pct,
        "justification_text": justification_text,
    })
    recount_prohibited(plan)
    touch(plan)
    if permissibility == "PROHIBITED":
        # Accepted into the draft, but the attempt goes on the record.
        audit.append("CompensationPlan", plan["id"], "PROHIBITED_VARIABLE_BLOCKED",
                     {"compensation_variable_id": row["id"],
                      "variable_type": variable_type,
                      "prohibited_variable_count": plan["prohibited_variable_count"]})
    return created(serializers.compensation_variable(row))


@bp.route("/compensation-plans/<row_id>/variables", methods=["GET"])
@endpoint(*ALL_ROLES)
def list_variables(row_id):
    plan = get_or_404(db.compensation_plans, row_id)
    rows = listing(db.compensation_variables,
                   lambda r: r["compensation_plan_id"] == plan["id"])
    return paginated(rows, serializers.compensation_variable)


@bp.route("/compensation-plans/<row_id>/approvals", methods=["POST"])
@endpoint("ComplianceOfficer")
def decide_plan(row_id):
    plan = get_or_404(db.compensation_plans, row_id)
    body = Body(raw_body())
    decision = body.enum("decision", DECISIONS)
    note = body.string("note", required=False, default=None, max_len=2000)
    gate("CompensationPlan", plan, ("DRAFT",))

    detail = {"decision": decision}
    if note is not None:
        detail["note"] = note

    if decision == "APPROVE":
        # Priority 16 -> 17 -> 25, exactly as PRD 2.9 fixes it.
        if plan["prohibited_variable_count"] >= 1:
            raise ApiError("ERR_PROHIBITED_COMP_VARIABLE")
        if g.user_id == plan["drafted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        children = variables_of(plan["id"])
        if not children or sum(v["weight_pct"] for v in children) != REQUIRED_WEIGHT_TOTAL:
            raise ApiError("ERR_PLAN_WEIGHTS_NOT_100")
        plan["status"] = "ACTIVE"
        plan["approved_by_user_id"] = g.user_id
        touch(plan)
        audit.append("CompensationPlan", plan["id"], "PLAN_APPROVED", detail)
        return ok(serializers.compensation_plan(plan))

    # A rejection must always be recordable: no prohibited-variable or weight test.
    if g.user_id == plan["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    plan["status"] = "REJECTED"
    plan["approved_by_user_id"] = g.user_id
    touch(plan)
    audit.append("CompensationPlan", plan["id"], "PLAN_REJECTED", detail)
    return ok(serializers.compensation_plan(plan))
