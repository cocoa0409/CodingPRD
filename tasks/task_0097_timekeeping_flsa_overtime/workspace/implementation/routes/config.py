"""Employer / wage rule set / worksite / employee configuration (PRD §3.1)."""
from flask import Blueprint, g

import db
from errors import err
from middleware import require_role
from response import object_response, array_response
from util import (
    as_bool, as_int, as_number, as_str, as_enum, body, paginate, pagination,
    public, public_list,
)
from services.helpers import get_or_404

bp = Blueprint("config", __name__)

WORKWEEK_DOWS = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------
@bp.post("/employers")
def create_employer():
    require_role("PayrollAdmin")
    data = body()
    legal_name = as_str(data, "legal_name", required=True)
    workweek_start_dow = as_enum(
        data, "workweek_start_dow", WORKWEEK_DOWS, required=False, default="MON"
    )
    federal_min_wage_cents = as_int(
        data, "federal_min_wage_cents", required=False, default=725
    )
    federal_tipped_cash_wage_cents = as_int(
        data, "federal_tipped_cash_wage_cents", required=False, default=213
    )

    record = db.base_fields()
    record.update({
        "legal_name": legal_name,
        "workweek_start_dow": workweek_start_dow,
        "federal_min_wage_cents": federal_min_wage_cents,
        "federal_tipped_cash_wage_cents": federal_tipped_cash_wage_cents,
    })
    db.employers[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/employers/<employer_id>")
def get_employer(employer_id):
    require_role("PayrollAdmin", "Supervisor")
    record = get_or_404(db.employers, employer_id)
    return object_response(public(record))


@bp.get("/employers/<employer_id>/wage-rulesets")
def list_employer_rulesets(employer_id):
    require_role("PayrollAdmin", "Supervisor")
    # Confirm parent exists first (PRD §2.7).
    get_or_404(db.employers, employer_id)
    limit, offset = pagination()
    matches = [r for r in db.wage_rulesets.values() if r.get("employer_id") == employer_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Wage rule sets
# ---------------------------------------------------------------------------
@bp.post("/wage-rulesets")
def create_wage_ruleset():
    require_role("PayrollAdmin")
    data = body()
    employer_id = as_str(data, "employer_id", required=True)
    state_code = as_str(data, "state_code", required=True)

    daily_ot_enabled = as_bool(data, "daily_ot_enabled", default=False)
    daily_ot_threshold_hours = as_number(
        data, "daily_ot_threshold_hours", required=False, default=8
    )
    daily_dt_threshold_hours = as_number(
        data, "daily_dt_threshold_hours", required=False, default=12
    )
    weekly_ot_threshold_hours = as_number(
        data, "weekly_ot_threshold_hours", required=False, default=40
    )
    seventh_day_rule_enabled = as_bool(data, "seventh_day_rule_enabled", default=False)
    meal_break_premium_enabled = as_bool(data, "meal_break_premium_enabled", default=False)
    rest_break_premium_enabled = as_bool(data, "rest_break_premium_enabled", default=False)
    state_min_wage_cents = as_int(data, "state_min_wage_cents", required=False, default=725)

    # Existence (priority 4) before the duplicate constraint (priority 23).
    get_or_404(db.employers, employer_id)

    # (employer_id, state_code) uniqueness -> ERR_DUPLICATE_RULESET.
    for r in db.wage_rulesets.values():
        if r.get("employer_id") == employer_id and r.get("state_code") == state_code:
            raise err("ERR_DUPLICATE_RULESET",
                      "A wage rule set for this employer and state already exists.")

    record = db.base_fields()
    record.update({
        "employer_id": employer_id,
        "state_code": state_code,
        "daily_ot_enabled": daily_ot_enabled,
        "daily_ot_threshold_hours": daily_ot_threshold_hours,
        "daily_dt_threshold_hours": daily_dt_threshold_hours,
        "weekly_ot_threshold_hours": weekly_ot_threshold_hours,
        "seventh_day_rule_enabled": seventh_day_rule_enabled,
        "meal_break_premium_enabled": meal_break_premium_enabled,
        "rest_break_premium_enabled": rest_break_premium_enabled,
        "state_min_wage_cents": state_min_wage_cents,
    })
    db.wage_rulesets[record["id"]] = record
    return object_response(public(record), 201)


# ---------------------------------------------------------------------------
# Worksites
# ---------------------------------------------------------------------------
@bp.post("/worksites")
def create_worksite():
    require_role("PayrollAdmin")
    data = body()
    employer_id = as_str(data, "employer_id", required=True)
    name = as_str(data, "name", required=True)
    state_code = as_str(data, "state_code", required=True)

    get_or_404(db.employers, employer_id)

    record = db.base_fields()
    record.update({
        "employer_id": employer_id,
        "name": name,
        "state_code": state_code,
    })
    db.worksites[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/worksites")
def list_worksites():
    require_role("PayrollAdmin", "Supervisor")
    limit, offset = pagination()
    from flask import request
    employer_id = request.args.get("employer_id")
    matches = list(db.worksites.values())
    if employer_id is not None:
        matches = [w for w in matches if w.get("employer_id") == employer_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/worksites/<worksite_id>")
def get_worksite(worksite_id):
    require_role("PayrollAdmin", "Supervisor")
    record = get_or_404(db.worksites, worksite_id)
    return object_response(public(record))


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
@bp.post("/employees")
def create_employee():
    require_role("PayrollAdmin")
    data = body()
    employer_id = as_str(data, "employer_id", required=True)
    home_worksite_id = as_str(data, "home_worksite_id", required=True)
    full_name = as_str(data, "full_name", required=True)
    classification = as_enum(
        data, "classification", {"EXEMPT", "NON_EXEMPT"}, required=True
    )
    base_rate_cents = as_int(data, "base_rate_cents", required=True)
    is_tipped = as_bool(data, "is_tipped", default=False)

    # Negative money is rejected with ERR_VALIDATION (priority 24).
    if base_rate_cents < 0:
        raise err("ERR_VALIDATION", "base_rate_cents must be non-negative.")

    # Existence (priority 4), validated left-to-right.
    get_or_404(db.employers, employer_id)
    get_or_404(db.worksites, home_worksite_id)

    record = db.base_fields()
    record.update({
        "employer_id": employer_id,
        "home_worksite_id": home_worksite_id,
        "full_name": full_name,
        "classification": classification,
        "base_rate_cents": base_rate_cents,
        "is_tipped": is_tipped,
        "status": "ACTIVE",
    })
    db.employees[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/employees")
def list_employees():
    require_role("PayrollAdmin", "Supervisor")
    limit, offset = pagination()
    from flask import request
    employer_id = request.args.get("employer_id")
    home_worksite_id = request.args.get("home_worksite_id")
    matches = list(db.employees.values())
    if employer_id is not None:
        matches = [e for e in matches if e.get("employer_id") == employer_id]
    if home_worksite_id is not None:
        matches = [e for e in matches if e.get("home_worksite_id") == home_worksite_id]
    page, total = paginate(matches, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/employees/<employee_id>")
def get_employee(employee_id):
    require_role("PayrollAdmin", "Supervisor", "Employee")
    record = get_or_404(db.employees, employee_id)
    return object_response(public(record))
