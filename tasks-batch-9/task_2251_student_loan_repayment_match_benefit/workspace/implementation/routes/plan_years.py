"""Plan years (PRD 3.1) and the annual true-up (PRD 3.8)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import (auth, body, opt_enum, opt_int, opt_number, opt_str,
                        req_enum, req_int, req_ts)
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("plan_years", __name__)

PLAN_YEAR_STATUSES = ("DRAFT", "OPEN", "LOCKED", "CLOSED")
TEST_METHODS = ("CURRENT_YEAR", "PRIOR_YEAR")

DEFAULT_COMPENSATION_CAP_CENTS = 34500000
DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS = 2300000
DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS = 15500000
DEFAULT_TIER1_PCT = 0.03
DEFAULT_TIER1_MATCH_RATE = 1.00
DEFAULT_TIER2_PCT = 0.02
DEFAULT_TIER2_MATCH_RATE = 0.50
DEFAULT_PRIOR_YEAR_NHCE_ACP = 0.0000
DEFAULT_UNPAID_LEAVE_DAY_CAP = 180
DEFAULT_LEAVE_MERGE_BUFFER_DAYS = 14


@bp.post("/plan-years")
def create_plan_year():
    auth("BenefitsAdministrator")
    payload = body()
    year = req_int(payload, "year", minimum=2024, maximum=2099)
    period_start, period_start_dt = req_ts(payload, "period_start")
    period_end, period_end_dt = req_ts(payload, "period_end")
    window_open, window_open_dt = req_ts(payload, "certification_window_open")
    deadline, deadline_dt = req_ts(payload, "certification_deadline")

    row = {
        "year": year,
        "status": "DRAFT",
        "period_start": period_start,
        "period_end": period_end,
        "certification_window_open": window_open,
        "certification_deadline": deadline,
        "compensation_cap_cents": opt_int(
            payload, "compensation_cap_cents",
            DEFAULT_COMPENSATION_CAP_CENTS, minimum=0),
        "annual_deferral_limit_cents": opt_int(
            payload, "annual_deferral_limit_cents",
            DEFAULT_ANNUAL_DEFERRAL_LIMIT_CENTS, minimum=0),
        "hce_prior_comp_threshold_cents": opt_int(
            payload, "hce_prior_comp_threshold_cents",
            DEFAULT_HCE_PRIOR_COMP_THRESHOLD_CENTS, minimum=0),
        "tier1_pct": opt_number(payload, "tier1_pct", DEFAULT_TIER1_PCT,
                                minimum=0),
        "tier1_match_rate": opt_number(payload, "tier1_match_rate",
                                       DEFAULT_TIER1_MATCH_RATE, minimum=0),
        "tier2_pct": opt_number(payload, "tier2_pct", DEFAULT_TIER2_PCT,
                                minimum=0),
        "tier2_match_rate": opt_number(payload, "tier2_match_rate",
                                       DEFAULT_TIER2_MATCH_RATE, minimum=0),
        "nondiscrimination_test_method": opt_enum(
            payload, "nondiscrimination_test_method", TEST_METHODS,
            "CURRENT_YEAR"),
        "prior_year_nhce_acp": opt_number(payload, "prior_year_nhce_acp",
                                          DEFAULT_PRIOR_YEAR_NHCE_ACP,
                                          minimum=0),
        "unpaid_leave_day_cap": opt_int(payload, "unpaid_leave_day_cap",
                                        DEFAULT_UNPAID_LEAVE_DAY_CAP,
                                        minimum=0),
        "leave_merge_buffer_days": opt_int(payload, "leave_merge_buffer_days",
                                           DEFAULT_LEAVE_MERGE_BUFFER_DAYS,
                                           minimum=0),
        "true_up_completed": False,
        "reopened_count": 0,
        "_period_start_dt": period_start_dt,
        "_period_end_dt": period_end_dt,
        "_window_open_dt": window_open_dt,
        "_deadline_dt": deadline_dt,
    }
    for existing in db.db.plan_years.values():
        if existing["year"] == year:
            fail("ERR_INVALID_REQUEST", "year %d already exists" % year)
    db.stamp_new(row)
    db.db.plan_years[row["id"]] = row
    return object_response(serialize.plan_year(row), 201)


@bp.get("/plan-years")
def list_plan_years():
    auth("BenefitsAdministrator", "PayrollOperator", "ComplianceAuditor",
         "Recordkeeper")
    rows = db.rows("plan_years")
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    year = request.args.get("year")
    if year:
        try:
            wanted = int(year)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "year must be an integer")
        rows = [r for r in rows if r["year"] == wanted]
    return paginated(rows, serialize.plan_year)


@bp.get("/plan-years/<plan_year_id>")
def get_plan_year(plan_year_id):
    auth("BenefitsAdministrator", "PayrollOperator", "ComplianceAuditor",
         "Recordkeeper")
    row = lookup.plan_year(plan_year_id)
    return object_response(serialize.plan_year(row))


@bp.post("/plan-years/<plan_year_id>/status")
def set_plan_year_status(plan_year_id):
    auth("BenefitsAdministrator")
    payload = body()
    to_status = req_enum(payload, "to_status", PLAN_YEAR_STATUSES)
    py = lookup.plan_year(plan_year_id)
    current = py["status"]
    transition = (current, to_status)
    if transition not in (("DRAFT", "OPEN"), ("OPEN", "LOCKED"),
                          ("LOCKED", "OPEN"), ("LOCKED", "CLOSED")):
        fail("ERR_INVALID_REQUEST",
             "plan year cannot move from %s to %s" % (current, to_status))

    if transition == ("OPEN", "LOCKED"):
        for cert in db.rows("loan_certifications"):
            if (cert["plan_year_id"] == py["id"]
                    and cert["status"] in ("SUBMITTED", "AUDIT_HOLD")):
                fail("ERR_CERTIFICATION_STATE_INVALID",
                     "a claim of this plan year is still in flight")
    elif transition == ("LOCKED", "CLOSED"):
        for batch in calc.batches_of_plan_year(py["id"]):
            if batch["status"] in ("PENDING", "TRANSMITTED"):
                fail("ERR_BATCH_STATE_INVALID",
                     "unsettled funding is still in flight")
    elif transition == ("LOCKED", "OPEN"):
        for test in db.rows("nondiscrimination_tests"):
            if (test["plan_year_id"] == py["id"]
                    and test["status"] in ("PASSED", "CORRECTED")):
                fail("ERR_TEST_ALREADY_FINAL",
                     "a finalized nondiscrimination test blocks the reopen")
    elif transition == ("DRAFT", "OPEN"):
        for other in db.rows("plan_years"):
            if other["id"] != py["id"] and other["status"] == "OPEN":
                fail("ERR_MULTIPLE_OPEN_PLAN_YEARS",
                     "another plan year is already OPEN")
        if not (py["_period_start_dt"] < py["_period_end_dt"]):
            fail("ERR_INVALID_REQUEST",
                 "period_start must be strictly earlier than period_end")
        if py["_window_open_dt"] > py["_deadline_dt"]:
            fail("ERR_INVALID_REQUEST",
                 "certification_window_open must be no later than "
                 "certification_deadline")

    py["status"] = to_status
    if transition == ("LOCKED", "OPEN"):
        py["reopened_count"] += 1
        py["true_up_completed"] = False
    db.touch(py)
    return object_response(serialize.plan_year(py))


@bp.post("/plan-years/<plan_year_id>/true-up")
def run_true_up(plan_year_id):
    user_id, _role = auth("BenefitsAdministrator")
    payload = body()
    employee_id = opt_str(payload, "employee_id")
    py = lookup.plan_year(plan_year_id)
    employee = lookup.employee(employee_id) if employee_id else None

    if py["status"] != "LOCKED":
        fail("ERR_PLAN_YEAR_NOT_LOCKED",
             "the true-up requires the plan year to be LOCKED")
    if py["true_up_completed"]:
        fail("ERR_TRUE_UP_ALREADY_RUN",
             "the true-up has already run for this plan year")

    if employee is not None:
        targets = [employee]
    else:
        targets = [e for e in db.rows("employees")
                   if calc.contribution_records_of(e["id"], py["id"])]

    summary = effects.run_true_up(py, targets, user_id)
    return object_response(summary)
