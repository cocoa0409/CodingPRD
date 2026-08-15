"""CensusEmployee, CompensationRecord, Contribution routes (PRD §3.4)."""

import re
from datetime import date
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_DUPLICATE, ERR_FK_INTEGRITY, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_LIMIT_EXCEEDED, ERR_INVALID_DATE_RANGE,
)
from middleware import READ_ROLES, ROLE_PLAN_ADMINISTRATOR, require_roles
from response import success_list, success_object
from services.common import (
    active_limit_for_year, bump, employees_of_year, get_body, get_contribution,
    get_employee, get_plan_year, new_entity, opt_bool, opt_date, opt_enum,
    opt_filter, opt_number, opt_string, page_slice, pagination_params,
    plan_year_of_contribution, plan_year_of_employee, req_bool, req_date,
    req_enum, req_int, req_number, req_string, touch,
)

bp = Blueprint("census", __name__)

EMPLOYMENT_STATUSES = {"ACTIVE", "TERMINATED", "LEAVE_OF_ABSENCE"}
COMP_SOURCES = {"W2", "SEC415", "SEC3401"}
COMP_PERIODS = {"CURRENT_YEAR", "PRIOR_YEAR"}
CONTRIBUTION_TYPES = {
    "ELECTIVE_DEFERRAL", "MATCH", "QNEC", "QMAC", "PROFIT_SHARING",
    "CAFETERIA_PRETAX", "DEPENDENT_CARE_ELECTIVE",
}
FORFEITABLE_TYPES = {"MATCH", "PROFIT_SHARING", "QNEC", "QMAC"}
SSN_RE = re.compile(r"^\d{9}$")

CONTRIBUTION_POSTING_STATES = {
    "CENSUS_COLLECTING", "CENSUS_LOCKED", "TESTING", "RESULTS_REVIEW", "CORRECTING",
}
FORFEIT_STATES = {"CENSUS_LOCKED", "TESTING", "RESULTS_REVIEW", "CORRECTING"}


def census_employee_out(e):
    return {
        "id": e["id"], "plan_year_id": e["plan_year_id"], "ssn": e["ssn"],
        "full_name": e["full_name"], "date_of_birth": e["date_of_birth"],
        "date_of_hire": e["date_of_hire"],
        "date_of_termination": e["date_of_termination"],
        "employment_status": e["employment_status"],
        "ownership_pct_direct": e["ownership_pct_direct"],
        "is_officer": e["is_officer"],
        "family_member_of_ssn": e["family_member_of_ssn"],
        "covered_status": e["covered_status"],
        "hce_status": e["hce_status"],
        "key_employee_status": e["key_employee_status"],
        "attributed_ownership_pct": e["attributed_ownership_pct"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def compensation_record_out(r):
    return {
        "id": r["id"], "census_employee_id": r["census_employee_id"],
        "comp_source": r["comp_source"], "amount_cents": r["amount_cents"],
        "period": r["period"], "source": r["source"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def contribution_out(c):
    return {
        "id": c["id"], "census_employee_id": c["census_employee_id"],
        "contribution_type": c["contribution_type"],
        "amount_cents": c["amount_cents"],
        "contribution_date": c["contribution_date"],
        "status": c["status"], "created_at": c["created_at"],
        "updated_at": c["updated_at"], "version": c["version"],
    }


def _require_census_collecting(py):
    if py["status"] != "CENSUS_COLLECTING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Census writes are permitted only while the plan year "
                       "is CENSUS_COLLECTING")


# ---------------------------------------------------------------------------
# Census employees
# ---------------------------------------------------------------------------

@bp.route("/ndt/plan-years/<pyid>/census-employees", methods=["GET"])
def list_census_employees(pyid):
    require_roles(READ_ROLES)
    get_plan_year(pyid)
    limit, offset = pagination_params()
    hce_status = opt_filter(request.args, "hce_status")
    covered_status = opt_filter(request.args, "covered_status")
    items = employees_of_year(pyid)
    if hce_status is not None:
        items = [e for e in items if e["hce_status"] == hce_status]
    if covered_status is not None:
        items = [e for e in items if e["covered_status"] == covered_status]
    page, total = page_slice(items, limit, offset)
    return success_list([census_employee_out(e) for e in page], limit, offset, total)


@bp.route("/ndt/plan-years/<pyid>/census-employees", methods=["POST"])
def create_census_employee(pyid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    py = get_plan_year(pyid)
    _require_census_collecting(py)
    body = get_body()
    ssn = req_string(body, "ssn")
    full_name = req_string(body, "full_name")
    date_of_birth = req_date(body, "date_of_birth")
    date_of_hire = req_date(body, "date_of_hire")
    date_of_termination = opt_date(body, "date_of_termination")
    employment_status = req_enum(body, "employment_status", EMPLOYMENT_STATUSES)
    ownership_pct_direct = opt_number(body, "ownership_pct_direct", Decimal(0))
    is_officer = opt_bool(body, "is_officer", False)
    family_member_of_ssn = opt_string(body, "family_member_of_ssn")
    if not SSN_RE.match(ssn):
        raise ApiError(ERR_INVALID_REQUEST, 400, "ssn must be exactly 9 digits")
    if ownership_pct_direct < 0 or ownership_pct_direct > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "ownership_pct_direct must be between 0 and 100")
    existing = employees_of_year(pyid)
    if any(e["ssn"] == ssn for e in existing):
        raise ApiError(ERR_DUPLICATE, 409, "ssn must be unique within the plan year")
    if family_member_of_ssn is not None:
        if not any(e["ssn"] == family_member_of_ssn for e in existing):
            raise ApiError(ERR_FK_INTEGRITY, 422,
                           "family_member_of_ssn must reference an existing "
                           "CensusEmployee.ssn within the same plan year")
    employee = new_entity({
        "plan_year_id": pyid, "ssn": ssn, "full_name": full_name,
        "date_of_birth": date_of_birth.isoformat(),
        "date_of_hire": date_of_hire.isoformat(),
        "date_of_termination": date_of_termination.isoformat() if date_of_termination else None,
        "employment_status": employment_status,
        "ownership_pct_direct": float(ownership_pct_direct),
        "is_officer": is_officer,
        "family_member_of_ssn": family_member_of_ssn,
        "covered_status": "INELIGIBLE",
        "hce_status": "NHCE",
        "key_employee_status": "NON_KEY",
        "attributed_ownership_pct": float(ownership_pct_direct),
    })
    store.census_employees[employee["id"]] = employee
    bump(py)
    return success_object(census_employee_out(employee), status=201)


@bp.route("/ndt/census-employees/<eid>", methods=["GET"])
def fetch_census_employee(eid):
    require_roles(READ_ROLES)
    return success_object(census_employee_out(get_employee(eid)))


@bp.route("/ndt/census-employees/<eid>", methods=["PATCH"])
def update_census_employee(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    employee = get_employee(eid)
    py = plan_year_of_employee(employee)
    _require_census_collecting(py)
    body = get_body()
    if "full_name" in body:
        employee["full_name"] = req_string(body, "full_name")
    if "date_of_birth" in body:
        employee["date_of_birth"] = req_date(body, "date_of_birth").isoformat()
    if "date_of_hire" in body:
        employee["date_of_hire"] = req_date(body, "date_of_hire").isoformat()
    if "date_of_termination" in body:
        value = opt_date(body, "date_of_termination")
        employee["date_of_termination"] = value.isoformat() if value else None
    if "employment_status" in body:
        employee["employment_status"] = req_enum(body, "employment_status",
                                                 EMPLOYMENT_STATUSES)
    if "ownership_pct_direct" in body:
        value = req_number(body, "ownership_pct_direct")
        if value < 0 or value > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "ownership_pct_direct must be between 0 and 100")
        employee["ownership_pct_direct"] = float(value)
    if "is_officer" in body:
        employee["is_officer"] = req_bool(body, "is_officer")
    if "family_member_of_ssn" in body:
        value = opt_string(body, "family_member_of_ssn")
        if value is not None:
            peers = employees_of_year(py["id"])
            if not any(e["ssn"] == value for e in peers):
                raise ApiError(ERR_FK_INTEGRITY, 422,
                               "family_member_of_ssn must reference an existing "
                               "CensusEmployee.ssn within the same plan year")
        employee["family_member_of_ssn"] = value
    bump(employee)
    bump(py)
    return success_object(census_employee_out(employee))


# ---------------------------------------------------------------------------
# Compensation records
# ---------------------------------------------------------------------------

@bp.route("/ndt/census-employees/<eid>/compensation-records", methods=["GET"])
def list_compensation_records(eid):
    require_roles(READ_ROLES)
    get_employee(eid)
    limit, offset = pagination_params()
    comp_source = opt_filter(request.args, "comp_source")
    period = opt_filter(request.args, "period")
    items = [r for r in store.compensation_records.values()
             if r["census_employee_id"] == eid]
    if comp_source is not None:
        items = [r for r in items if r["comp_source"] == comp_source]
    if period is not None:
        items = [r for r in items if r["period"] == period]
    page, total = page_slice(items, limit, offset)
    return success_list([compensation_record_out(r) for r in page], limit, offset, total)


@bp.route("/ndt/census-employees/<eid>/compensation-records", methods=["POST"])
def create_compensation_record(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    employee = get_employee(eid)
    py = plan_year_of_employee(employee)
    _require_census_collecting(py)
    body = get_body()
    comp_source = req_enum(body, "comp_source", COMP_SOURCES)
    amount_cents = req_int(body, "amount_cents")
    period = req_enum(body, "period", COMP_PERIODS)
    if amount_cents < 0:
        raise ApiError(ERR_LIMIT_EXCEEDED, 422,
                       "amount_cents must be zero or greater")
    record = new_entity({
        "census_employee_id": eid, "comp_source": comp_source,
        "amount_cents": amount_cents, "period": period, "source": "IMPORTED",
    })
    store.compensation_records[record["id"]] = record
    bump(py)
    return success_object(compensation_record_out(record), status=201)


# ---------------------------------------------------------------------------
# Contributions
# ---------------------------------------------------------------------------

@bp.route("/ndt/census-employees/<eid>/contributions", methods=["GET"])
def list_contributions(eid):
    require_roles(READ_ROLES)
    get_employee(eid)
    limit, offset = pagination_params()
    contribution_type = opt_filter(request.args, "contribution_type")
    status = opt_filter(request.args, "status")
    items = [c for c in store.contributions.values()
             if c["census_employee_id"] == eid]
    if contribution_type is not None:
        items = [c for c in items if c["contribution_type"] == contribution_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total = page_slice(items, limit, offset)
    return success_list([contribution_out(c) for c in page], limit, offset, total)


@bp.route("/ndt/census-employees/<eid>/contributions", methods=["POST"])
def create_contribution(eid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    employee = get_employee(eid)
    py = plan_year_of_employee(employee)
    if py["status"] not in CONTRIBUTION_POSTING_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Contributions may only be posted while the plan year is "
                       "between CENSUS_COLLECTING and CORRECTING")
    body = get_body()
    contribution_type = req_enum(body, "contribution_type", CONTRIBUTION_TYPES)
    amount_cents = req_int(body, "amount_cents")
    contribution_date = req_date(body, "contribution_date")
    year_start = date.fromisoformat(py["year_start"])
    year_end = date.fromisoformat(py["year_end"])
    if not (year_start <= contribution_date <= year_end):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "contribution_date must fall within the plan year")
    if amount_cents <= 0:
        raise ApiError(ERR_LIMIT_EXCEEDED, 422,
                       "amount_cents must be strictly positive")
    if contribution_type == "ELECTIVE_DEFERRAL":
        limit = active_limit_for_year(py["year_label"])
        if limit is not None:
            running = 0
            for c in store.contributions.values():
                if (c["census_employee_id"] == eid
                        and c["contribution_type"] == "ELECTIVE_DEFERRAL"
                        and c["status"] in ("POSTED", "PENDING_DISTRIBUTION")):
                    running += c["amount_cents"]
            if running + amount_cents > limit["sec402g_limit_cents"]:
                raise ApiError(ERR_LIMIT_EXCEEDED, 422,
                               "402(g) elective deferral limit exceeded")
    contribution = new_entity({
        "census_employee_id": eid, "contribution_type": contribution_type,
        "amount_cents": amount_cents,
        "contribution_date": contribution_date.isoformat(),
        "status": "POSTED",
    })
    store.contributions[contribution["id"]] = contribution
    bump(py)
    return success_object(contribution_out(contribution), status=201)


@bp.route("/ndt/contributions/<cid>", methods=["GET"])
def fetch_contribution(cid):
    require_roles(READ_ROLES)
    return success_object(contribution_out(get_contribution(cid)))


@bp.route("/ndt/contributions/<cid>/forfeit", methods=["POST"])
def forfeit_contribution(cid):
    require_roles({ROLE_PLAN_ADMINISTRATOR})
    contribution = get_contribution(cid)
    py = plan_year_of_contribution(contribution)
    if py is not None and py["status"] not in FORFEIT_STATES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Forfeiture requires the plan year to be between "
                       "CENSUS_LOCKED and CORRECTING")
    if contribution["status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a POSTED contribution can be forfeited")
    if contribution["contribution_type"] not in FORFEITABLE_TYPES:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only employer-source contributions (MATCH, PROFIT_SHARING, "
                       "QNEC, QMAC) can be forfeited")
    contribution["status"] = "FORFEITED"
    bump(contribution)
    from services.common import supersede_terminal_test_runs
    supersede_terminal_test_runs(py["id"])
    return success_object(contribution_out(contribution))
