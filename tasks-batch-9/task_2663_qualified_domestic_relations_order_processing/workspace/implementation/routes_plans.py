"""Plan registration, procedures lifecycle, and the plan's participant list."""
from flask import Blueprint

import auth
import enums
import errors
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from store import db, order_by, public, public_list

bp = Blueprint("plans", __name__)


def participant_rows(plan_id):
    rows = [r for r in db.participants.values() if r["plan_id"] == plan_id]
    return order_by(rows, "created_at")


def plan_view(plan):
    row = public(plan)
    row["participant_count"] = len(participant_rows(plan["id"]))
    return row


def find_plan(plan_id):
    plan = db.plans.get(plan_id)
    if plan is None:
        errors.fail(errors.ERR_PLAN_NOT_FOUND, "No plan with that id.")
    return plan


@bp.route("/plans", methods=["POST"])
@endpoint("PlanAdministrator")
def create_plan(caller):
    data = v.body()
    fields = {
        "plan_name": v.req_string(data, "plan_name", 1, 120),
        "plan_type": v.req_enum(data, "plan_type", enums.PLAN_TYPES),
        "model_language_version": v.req_string(data, "model_language_version", 1, 32),
        "acceptable_formula_codes": v.req_enum_array(
            data, "acceptable_formula_codes", enums.FORMULA_CODES, non_empty=True),
        "allowed_approaches": v.req_enum_array(
            data, "allowed_approaches", enums.APPROACHES, non_empty=True),
        "requires_model_language": v.opt_bool(data, "requires_model_language", True),
        "permits_benefit_not_otherwise_available": v.opt_bool(
            data, "permits_benefit_not_otherwise_available", False),
        "review_period_days": v.opt_int(data, "review_period_days", 1, 365, 45),
        "segregation_period_days": v.opt_int(data, "segregation_period_days", 1, 1095, 548),
        "resubmission_window_days": v.opt_int(data, "resubmission_window_days", 1, 365, 60),
        "max_revisions": v.opt_int(data, "max_revisions", 1, 10, 3),
        "earnings_adjustment_method": v.req_enum(
            data, "earnings_adjustment_method", enums.EARNINGS_METHODS),
        "max_assignable_pct_bps": v.opt_int(data, "max_assignable_pct_bps", 1, 10000, 5000),
        "max_assignable_amount_cents": v.opt_int(
            data, "max_assignable_amount_cents", 1, None, 100000000),
        "procedures_status": "DRAFT",
        "participant_count": 0,
    }
    plan = db.new_row("Plan", fields)
    db.plans[plan["id"]] = plan
    return object_response(plan_view(plan), 201)


@bp.route("/plans/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst")
def read_plan(caller, id):
    plan = find_plan(id)
    return object_response(plan_view(plan))


@bp.route("/plans/<id>/procedure-status", methods=["POST"])
@endpoint("PlanAdministrator")
def move_procedure_status(caller, id):
    data = v.body()
    to_status = v.req_enum(data, "to_status", enums.PROCEDURES_STATUSES)
    plan = find_plan(id)
    current = plan["procedures_status"]
    if (current, to_status) not in enums.PROCEDURE_TRANSITIONS:
        errors.fail(errors.ERR_PROCEDURE_STATUS_TRANSITION_INVALID,
                    "%s -> %s is not a declared procedures transition." % (current, to_status))
    if to_status == "PUBLISHED":
        # Published procedures with nothing declared acceptable would qualify nothing.
        if not plan["acceptable_formula_codes"] or not plan["allowed_approaches"]:
            errors.fail(errors.ERR_PROCEDURE_STATUS_TRANSITION_INVALID,
                        "Publication requires acceptable formulas and allowed approaches.")
    plan["procedures_status"] = to_status
    db.touch(plan)
    return object_response(plan_view(plan))


@bp.route("/plans/<id>/participants", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst")
def list_plan_participants(caller, id):
    employment_status = v.query_enum("employment_status", enums.EMPLOYMENT_STATUSES)
    plan = find_plan(id)
    rows = participant_rows(plan["id"])
    if employment_status is not None:
        rows = [r for r in rows if r["employment_status"] == employment_status]
    return paginate(public_list(rows))
