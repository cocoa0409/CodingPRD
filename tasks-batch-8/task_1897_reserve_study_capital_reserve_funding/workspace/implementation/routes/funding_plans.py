"""FundingPlan endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_STUDY_NOT_DRAFT, ERR_STALE_VERSION, ERR_PLAN_TYPE_LOCKED,
    ERR_PLAN_ALREADY_SELECTED,
)
from services.calculations import solve_funding_plan

bp = Blueprint("funding_plans", __name__)

VALID_PLAN_TYPES = {"BASELINE", "THRESHOLD", "FULL"}


def serialize_plan(plan):
    return {
        "id": plan["id"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
        "version": plan["version"],
        "study_id": plan["study_id"],
        "plan_type": plan["plan_type"],
        "status": plan["status"],
        "starting_cash_cents": plan["starting_cash_cents"],
        "annual_contribution_cents": plan["annual_contribution_cents"],
        "threshold_floor_cents": plan.get("threshold_floor_cents"),
        "computed_at": plan["computed_at"],
    }


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


@bp.route("/reserve-studies/<id>/funding-plans", methods=["POST"])
def create_funding_plan(id):
    require_roles("ReserveSpecialist")
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    body = request.get_json(force=True, silent=True) or {}
    required = ["plan_type", "expected_study_version"]
    allowed = set(required)
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    plan_type = body["plan_type"]
    expected_version = body["expected_study_version"]

    if plan_type not in VALID_PLAN_TYPES:
        raise make_error(ERR_INVALID_REQUEST, f"Invalid plan_type: {plan_type}")
    if not isinstance(expected_version, int):
        raise make_error(ERR_INVALID_REQUEST, "expected_study_version must be an integer")

    # Study must be DRAFT
    if study["status"] != "DRAFT":
        raise make_error(ERR_STUDY_NOT_DRAFT, f"Study is {study['status']}, not DRAFT")

    # OCC check
    if expected_version != study["version"]:
        raise make_error(ERR_STALE_VERSION, f"Expected version {expected_version}, actual {study['version']}")

    # Check same-type plan
    existing_same_type = [
        p for p in store.funding_plans.values()
        if p["study_id"] == id and p["plan_type"] == plan_type and p["status"] != "RETIRED"
    ]
    for ep in existing_same_type:
        if ep["status"] in ("RECOMMENDED", "SELECTED"):
            raise make_error(ERR_PLAN_TYPE_LOCKED, f"A {plan_type} plan in {ep['status']} exists")
        elif ep["status"] == "DRAFT":
            # Retire old DRAFT plan
            ep["status"] = "RETIRED"
            store.touch(ep)

    # Compute the plan
    assoc = store.associations[study["association_id"]]
    starting_cash = assoc["reserve_cash_balance_cents"]
    annual_contribution, threshold_floor = solve_funding_plan(study, plan_type, starting_cash)

    plan = store.make_common_fields()
    plan.update({
        "study_id": id,
        "plan_type": plan_type,
        "status": "DRAFT",
        "starting_cash_cents": starting_cash,
        "annual_contribution_cents": annual_contribution,
        "threshold_floor_cents": threshold_floor,
        "computed_at": store.now_iso(),
    })
    store.funding_plans[plan["id"]] = plan

    # Plan creation bumps study version
    store.touch(study)

    return success_object(serialize_plan(plan), 201)


@bp.route("/reserve-studies/<id>/funding-plans", methods=["GET"])
def list_funding_plans(id):
    require_roles(*ANY_ROLE)
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    plans = [p for p in store.funding_plans.values() if p["study_id"] == id]

    plan_type_filter = request.args.get("plan_type")
    if plan_type_filter:
        plans = [p for p in plans if p["plan_type"] == plan_type_filter]

    status_filter = request.args.get("status")
    if status_filter:
        plans = [p for p in plans if p["status"] == status_filter]

    plans.sort(key=lambda p: p["created_at"])
    limit, offset = _parse_pagination()
    total = len(plans)
    page = plans[offset:offset + limit]
    return success_list([serialize_plan(p) for p in page], total, limit, offset)


@bp.route("/funding-plans/<id>/recommend", methods=["POST"])
def recommend_plan(id):
    require_roles("ReserveSpecialist")
    plan = store.funding_plans.get(id)
    if not plan:
        raise make_error(ERR_NOT_FOUND, f"FundingPlan {id} not found")

    study = store.reserve_studies.get(plan["study_id"])
    if not study:
        raise make_error(ERR_NOT_FOUND, f"Study not found")

    # Plan must be DRAFT
    if plan["status"] != "DRAFT":
        raise make_error(ERR_INVALID_STATE, f"Plan is {plan['status']}, not DRAFT")

    # Study must be DRAFT or SUBMITTED
    if study["status"] not in ("DRAFT", "SUBMITTED"):
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}")

    # Revert any other RECOMMENDED plan of same study to DRAFT
    for p in store.funding_plans.values():
        if p["study_id"] == plan["study_id"] and p["status"] == "RECOMMENDED" and p["id"] != id:
            p["status"] = "DRAFT"
            store.touch(p)

    plan["status"] = "RECOMMENDED"
    store.touch(plan)
    return success_object(serialize_plan(plan))


@bp.route("/funding-plans/<id>/select", methods=["POST"])
def select_plan(id):
    require_roles("BoardMember")
    plan = store.funding_plans.get(id)
    if not plan:
        raise make_error(ERR_NOT_FOUND, f"FundingPlan {id} not found")

    study = store.reserve_studies.get(plan["study_id"])
    if not study:
        raise make_error(ERR_NOT_FOUND, f"Study not found")

    # Study must be SUBMITTED
    if study["status"] != "SUBMITTED":
        raise make_error(ERR_INVALID_STATE, f"Study is {study['status']}, not SUBMITTED")

    # Plan must be DRAFT or RECOMMENDED
    if plan["status"] not in ("DRAFT", "RECOMMENDED"):
        raise make_error(ERR_INVALID_STATE, f"Plan is {plan['status']}")

    # No other plan SELECTED
    for p in store.funding_plans.values():
        if p["study_id"] == plan["study_id"] and p["status"] == "SELECTED" and p["id"] != id:
            raise make_error(ERR_PLAN_ALREADY_SELECTED, "Another plan is already SELECTED")

    plan["status"] = "SELECTED"
    store.touch(plan)
    return success_object(serialize_plan(plan))
