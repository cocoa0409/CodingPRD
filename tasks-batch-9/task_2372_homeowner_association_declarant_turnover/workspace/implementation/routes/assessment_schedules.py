"""Assessment schedules: the budget re-forecast and its adoption."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import response
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("assessment_schedules", __name__)


@bp.post("/hoa/assessment-schedules")
def create_schedule():
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    fiscal_year = v.get_int(
        body,
        "fiscal_year",
        minimum=constants.FISCAL_YEAR_MIN,
        maximum=constants.FISCAL_YEAR_MAX,
    )
    projected_cost = v.get_int(body, "projected_operating_cost_cents", minimum=0)
    expected_version = v.get_int(body, "expected_association_version")

    # ---- ladder step 7: optimistic concurrency on the association ----
    if expected_version != association["version"]:
        raise ApiError("ERR_STALE_ASSOCIATION_VERSION")

    cascades.require_not_settled_locked(association["id"])

    case = calc.case_for_association(association["id"])
    if case is None or case["financial_status"] == "SUBSIDY_ACTIVE":
        raise ApiError("ERR_SUBSIDY_STILL_ACTIVE")
    if calc.adopted_study(association["id"]) is None:
        raise ApiError("ERR_RESERVE_STUDY_NOT_ADOPTED")

    for existing in calc.schedules_of(association["id"]):
        if existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    schedule = new_record({
        "association_id": association["id"],
        "fiscal_year": fiscal_year,
        "projected_operating_cost_cents": projected_cost,
        "billable_lot_count": 0,
        "reserve_contribution_cents": 0,
        "subsidy_offset_cents": 0,
        "annual_requirement_cents": 0,
        "per_lot_monthly_assessment_cents": 0,
        "annual_budget_total_cents": 0,
        "residual_cents": 0,
        "increase_pct_vs_prior": 0.00,
        "owner_vote_required": False,
        "owner_vote_ratified": False,
        "status": "DRAFT",
    })
    calc.apply_assessment_reforecast(schedule, association)
    db.assessment_schedules[schedule["id"]] = schedule

    touch(association)
    return response.object_response(serialize(schedule), 201)


@bp.post("/hoa/assessment-schedules/<schedule_id>/adopt")
def adopt_schedule(schedule_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    schedule = common.assessment_schedule_or_404(schedule_id, scoped=True)
    body = v.body()
    ratified = v.get_bool(body, "owner_vote_ratified", required=False, default=False)

    cascades.require_not_settled_locked(schedule["association_id"])

    if schedule["status"] != "DRAFT":
        raise ApiError("ERR_NOT_IN_DRAFT")
    if schedule["owner_vote_required"] and ratified is not True:
        raise ApiError("ERR_OWNER_VOTE_REQUIRED")

    association = db.associations[schedule["association_id"]]

    for existing in calc.schedules_of(association["id"]):
        if existing["id"] != schedule["id"] and existing["status"] == "ADOPTED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    schedule["status"] = "ADOPTED"
    schedule["owner_vote_ratified"] = ratified
    touch(schedule)

    association["reserve_pool_cents"] += schedule["residual_cents"]
    association["budget_forecast_status"] = "CURRENT"
    touch(association)

    return response.object_response(serialize(schedule))
