"""BenefitPlan design, amendment and activation."""

from flask import Blueprint

from db import clock, db
from errors import ApiError
from middleware import auth, json_body
from response import ok, paginate
from util import (
    D,
    check_range,
    opt_enum,
    opt_int_field,
    opt_num_field,
    parse_dt_value,
    present,
    req_int_field,
    req_str,
)

from services.core import new_row, s_plan, sort_created, touch
from routes._common import DEPENDENT_TYPES, PLAN_STATUSES, keep, need, qs_enum, qs_str

bp = Blueprint("plans", __name__)


def _hours(body, key):
    value = opt_num_field(body, key)
    if value is None:
        return None
    if value <= 0 or value > D(12):
        raise ApiError("ERR_INVALID_REQUEST")
    if (D(value) / D("0.25")) % 1 != 0:
        raise ApiError("ERR_INVALID_REQUEST")
    return D(value)


def _dependent_types(body, key, required):
    if key not in body or body[key] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST")
        return None
    value = body[key]
    if not isinstance(value, list) or len(value) == 0:
        raise ApiError("ERR_INVALID_REQUEST")
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in DEPENDENT_TYPES:
            raise ApiError("ERR_INVALID_REQUEST")
        if item in seen:
            raise ApiError("ERR_INVALID_REQUEST")
        seen.add(item)
    return list(value)


def _ranged_int(body, key, low, high, required):
    if required:
        value = req_int_field(body, key)
    else:
        value = opt_int_field(body, key)
    return check_range(value, low, high)


@bp.post("/benefit-plans")
def create_plan():
    body = json_body()
    employer_id = req_str(body, "employer_id")
    expected_version = req_int_field(body, "expected_employer_version")
    plan_code = req_str(body, "plan_code", 80)
    annual_use_limit_days = _ranged_int(body, "annual_use_limit_days", 1, 60, True)
    copay_center = _ranged_int(body, "copay_center_cents_per_day", 0, 100000, True)
    copay_in_home = _ranged_int(body, "copay_in_home_cents_per_hour", 0, 100000, True)
    min_hours = _hours(body, "in_home_min_billable_hours")
    dependent_types = _dependent_types(body, "eligible_dependent_types", True)
    max_dependents = _ranged_int(body, "max_dependents_per_reservation", 1, 6, False)
    overage_center = _ranged_int(
        body, "overage_rate_center_cents_per_day", 0, 500000, True
    )
    overage_in_home = _ranged_int(
        body, "overage_rate_in_home_cents_per_hour", 0, 500000, True
    )
    cancellation_window = _ranged_int(body, "cancellation_window_hours", 0, 168, False)
    no_show_charge = _ranged_int(body, "no_show_charge_cents", 0, 200000, True)
    if not present(body, "effective_from"):
        raise ApiError("ERR_INVALID_REQUEST")
    effective_from = parse_dt_value(body["effective_from"])
    effective_to = (
        parse_dt_value(body["effective_to"]) if present(body, "effective_to") else None
    )

    auth("benefits_admin")

    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError("ERR_EMPLOYER_NOT_FOUND")

    if expected_version != employer["version"]:
        raise ApiError("ERR_STALE_EMPLOYER_VERSION")

    for row in db.benefit_plans.values():
        if row["employer_id"] != employer_id:
            continue
        if row["plan_code"] != plan_code:
            continue
        if row["status"] in ("DRAFT", "ACTIVE"):
            raise ApiError("ERR_DUPLICATE_KEY")

    plan = new_row(
        {
            "employer_id": employer_id,
            "plan_code": plan_code,
            "annual_use_limit_days": annual_use_limit_days,
            "copay_center_cents_per_day": copay_center,
            "copay_in_home_cents_per_hour": copay_in_home,
            "in_home_min_billable_hours": D(4) if min_hours is None else min_hours,
            "eligible_dependent_types": dependent_types,
            "max_dependents_per_reservation": 3
            if max_dependents is None
            else max_dependents,
            "overage_rate_center_cents_per_day": overage_center,
            "overage_rate_in_home_cents_per_hour": overage_in_home,
            "cancellation_window_hours": 24
            if cancellation_window is None
            else cancellation_window,
            "no_show_charge_cents": no_show_charge,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "DRAFT",
            "superseded_by_plan_id": None,
        }
    )
    db.benefit_plans[plan["id"]] = plan
    return ok(s_plan(plan), 201)


@bp.get("/benefit-plans/<row_id>")
def get_plan(row_id):
    auth("network_admin", "benefits_admin", "care_coordinator", "employee_user")
    plan = need(db.benefit_plans, row_id, "ERR_BENEFITPLAN_NOT_FOUND")
    return ok(s_plan(plan))


@bp.get("/benefit-plans")
def list_plans():
    auth("network_admin", "benefits_admin", "care_coordinator")
    employer_id = qs_str("employer_id")
    status = qs_enum("status", PLAN_STATUSES)
    superseded_by = qs_str("superseded_by_plan_id")
    rows = sort_created(list(db.benefit_plans.values()))
    rows = keep(rows, "employer_id", employer_id)
    rows = keep(rows, "status", status)
    rows = keep(rows, "superseded_by_plan_id", superseded_by)
    return paginate(rows, s_plan)


@bp.patch("/benefit-plans/<row_id>")
def patch_plan(row_id):
    body = json_body()
    annual_use_limit_days = _ranged_int(body, "annual_use_limit_days", 1, 60, False)
    copay_center = _ranged_int(body, "copay_center_cents_per_day", 0, 100000, False)
    copay_in_home = _ranged_int(body, "copay_in_home_cents_per_hour", 0, 100000, False)
    min_hours = _hours(body, "in_home_min_billable_hours")
    dependent_types = _dependent_types(body, "eligible_dependent_types", False)
    max_dependents = _ranged_int(body, "max_dependents_per_reservation", 1, 6, False)
    overage_center = _ranged_int(
        body, "overage_rate_center_cents_per_day", 0, 500000, False
    )
    overage_in_home = _ranged_int(
        body, "overage_rate_in_home_cents_per_hour", 0, 500000, False
    )
    cancellation_window = _ranged_int(body, "cancellation_window_hours", 0, 168, False)
    no_show_charge = _ranged_int(body, "no_show_charge_cents", 0, 200000, False)
    effective_to = (
        parse_dt_value(body["effective_to"]) if present(body, "effective_to") else None
    )

    auth("benefits_admin")
    plan = need(db.benefit_plans, row_id, "ERR_BENEFITPLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_EDITABLE")

    updates = {
        "annual_use_limit_days": annual_use_limit_days,
        "copay_center_cents_per_day": copay_center,
        "copay_in_home_cents_per_hour": copay_in_home,
        "in_home_min_billable_hours": min_hours,
        "eligible_dependent_types": dependent_types,
        "max_dependents_per_reservation": max_dependents,
        "overage_rate_center_cents_per_day": overage_center,
        "overage_rate_in_home_cents_per_hour": overage_in_home,
        "cancellation_window_hours": cancellation_window,
        "no_show_charge_cents": no_show_charge,
        "effective_to": effective_to,
    }
    for key, value in updates.items():
        if value is not None:
            plan[key] = value
    touch(plan)
    return ok(s_plan(plan))


@bp.post("/benefit-plans/<row_id>/activate")
def activate_plan(row_id):
    json_body()
    auth("benefits_admin")
    plan = need(db.benefit_plans, row_id, "ERR_BENEFITPLAN_NOT_FOUND")

    if plan["status"] == "SUPERSEDED":
        raise ApiError("ERR_BENEFITPLAN_TERMINAL")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_BENEFITPLAN_STATE_INVALID")

    employer = db.employers.get(plan["employer_id"])
    if employer is None or employer["contract_status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYER_CONTRACT_INACTIVE")

    now = clock()
    if plan["effective_from"] > now:
        raise ApiError("ERR_PLAN_EFFECTIVE_WINDOW")
    if plan["effective_to"] is not None and now >= plan["effective_to"]:
        raise ApiError("ERR_PLAN_EFFECTIVE_WINDOW")

    incumbent = None
    for row in sort_created(list(db.benefit_plans.values())):
        if row["employer_id"] != plan["employer_id"]:
            continue
        if row["id"] == plan["id"]:
            continue
        if row["status"] == "ACTIVE":
            incumbent = row
            break

    if incumbent is not None and incumbent["effective_from"] >= plan["effective_from"]:
        raise ApiError("ERR_ACTIVE_PLAN_EXISTS")

    plan["status"] = "ACTIVE"
    touch(plan)
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        incumbent["superseded_by_plan_id"] = plan["id"]
        touch(incumbent)
    return ok(s_plan(plan))
