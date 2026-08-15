"""Plan endpoints."""
from flask import Blueprint

import db
from errors import (
    ERR_PLAN_STATE_INVALID,
    ERR_STALE_VERSION,
    raise_err,
)
from middleware import user_context, require_role
from response import ok_object, ok_list
from services.core import (
    body,
    req_string,
    req_date,
    req_string_list,
    opt_bool,
    opt_enum,
    opt_int,
    req_int,
    get_or_404,
    stamp_new,
    touch,
    void_open_elections_for_plan,
)
from util import CLOCK, fmt_date, parse_date, add_months

bp = Blueprint("plans", __name__)

DISTRIBUTION_EVENTS = {
    "SEPARATION",
    "DEATH",
    "DISABILITY",
    "FIXED_TIME",
    "UNFORESEEABLE_EMERGENCY",
    "CHANGE_IN_CONTROL",
}


def plan_view(plan):
    return {
        "id": plan["id"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
        "version": plan["version"],
        "name": plan["name"],
        "effective_date": plan["effective_date"],
        "distribution_events_allowed": list(plan["distribution_events_allowed"]),
        "six_month_delay_enabled": plan["six_month_delay_enabled"],
        "rabbi_trust_required": plan["rabbi_trust_required"],
        "accelerate_on_cic": plan["accelerate_on_cic"],
        "separation_fraction_test": plan["separation_fraction_test"],
        "vesting_cliff_years": plan["vesting_cliff_years"],
        "officer_comp_threshold_cents": plan["officer_comp_threshold_cents"],
        "processing_lag_days": plan["processing_lag_days"],
        "status": plan["status"],
        "document_posture": plan["document_posture"],
        "termination_effective_date": plan["termination_effective_date"],
        "open_findings_count": plan["open_findings_count"],
    }


def _list_response(items, args):
    from errors import ERR_INVALID_REQUEST

    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list(page, total, limit, offset)


@bp.post("/api/plans")
def create_plan():
    data = body()
    name = req_string(data, "name")
    effective = req_date(data, "effective_date")
    events = req_string_list(data, "distribution_events_allowed", members=DISTRIBUTION_EVENTS, non_empty=True)
    threshold = req_int(data, "officer_comp_threshold_cents", lo=1)
    six_month = opt_bool(data, "six_month_delay_enabled", True)
    trust_required = opt_bool(data, "rabbi_trust_required", False)
    accel = opt_bool(data, "accelerate_on_cic", False)
    test = opt_enum(data, "separation_fraction_test", {"DEFAULT_50", "LIBERAL_20"}, "DEFAULT_50")
    cliff = opt_int(data, "vesting_cliff_years", 1, 10)
    if cliff is None:
        cliff = 3
    lag = opt_int(data, "processing_lag_days", 0, 90)
    if lag is None:
        lag = 30
    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = stamp_new(
        {
            "name": name,
            "effective_date": fmt_date(effective),
            "distribution_events_allowed": events,
            "six_month_delay_enabled": six_month,
            "rabbi_trust_required": trust_required,
            "accelerate_on_cic": accel,
            "separation_fraction_test": test,
            "vesting_cliff_years": cliff,
            "officer_comp_threshold_cents": threshold,
            "processing_lag_days": lag,
            "status": "DRAFT",
            "document_posture": "COMPLIANT",
            "termination_effective_date": None,
            "open_findings_count": 0,
        }
    )
    db.plans[plan["id"]] = plan
    return ok_object(plan_view(plan), 201)


@bp.get("/api/plans")
def list_plans():
    user_context()
    from flask import request

    return _list_response([plan_view(p) for p in db.plans.values()], request.args)


@bp.get("/api/plans/<planId>")
def get_plan(planId):
    user_context()
    plan = get_or_404(db.plans, planId, "Plan")
    return ok_object(plan_view(plan))


@bp.patch("/api/plans/<planId>")
def amend_plan(planId):
    data = body()
    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, planId, "Plan")
    expected = req_int(data, "expected_plan_version")
    if expected != plan["version"]:
        raise_err(ERR_STALE_VERSION, "expected_plan_version does not match current Plan.version")
    if plan["status"] in ("TERMINATION_PENDING", "TERMINATED"):
        raise_err(ERR_PLAN_STATE_INVALID, "Plan may not be amended once termination has begun")

    if "name" in data:
        plan["name"] = req_string(data, "name")
    for f in ("six_month_delay_enabled", "rabbi_trust_required", "accelerate_on_cic"):
        if f in data:
            plan[f] = opt_bool(data, f, plan[f])
    if "separation_fraction_test" in data:
        plan["separation_fraction_test"] = opt_enum(
            data, "separation_fraction_test", {"DEFAULT_50", "LIBERAL_20"}, plan["separation_fraction_test"]
        )
    if "vesting_cliff_years" in data:
        plan["vesting_cliff_years"] = opt_int(data, "vesting_cliff_years", 1, 10)
    if "officer_comp_threshold_cents" in data:
        plan["officer_comp_threshold_cents"] = opt_int(data, "officer_comp_threshold_cents", lo=1)
    if "processing_lag_days" in data:
        plan["processing_lag_days"] = opt_int(data, "processing_lag_days", 0, 90)
    touch(plan)
    return ok_object(plan_view(plan))


def _transition(planId, from_states, to_state, extra=None):
    body()
    user_id, role = user_context()
    require_role(role, {"PlanSponsor"})
    plan = get_or_404(db.plans, planId, "Plan")
    if plan["status"] not in from_states:
        raise_err(ERR_PLAN_STATE_INVALID, f"Plan transition requires status in {sorted(from_states)}")
    plan["status"] = to_state
    if extra:
        extra(plan)
    touch(plan)
    return ok_object(plan_view(plan))


@bp.post("/api/plans/<planId>/activate")
def activate_plan(planId):
    return _transition(planId, {"DRAFT"}, "ACTIVE")


@bp.post("/api/plans/<planId>/suspend")
def suspend_plan(planId):
    return _transition(planId, {"ACTIVE"}, "SUSPENDED")


@bp.post("/api/plans/<planId>/resume")
def resume_plan(planId):
    return _transition(planId, {"SUSPENDED"}, "ACTIVE")


@bp.post("/api/plans/<planId>/terminate")
def terminate_plan(planId):
    def _term(plan):
        plan["termination_effective_date"] = fmt_date(add_months(CLOCK.date(), 12))
        void_open_elections_for_plan(plan["id"])

    return _transition(planId, {"ACTIVE", "SUSPENDED"}, "TERMINATION_PENDING", _term)
