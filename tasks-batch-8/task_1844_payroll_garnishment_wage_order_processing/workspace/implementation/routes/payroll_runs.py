"""PayrollRun and PayStatement lifecycle (PRD §3.5, §3.6)."""

from flask import Blueprint, g

from db import logical_now, next_seq, store
from errors import (
    ERR_EMPLOYEE_TERMINATED_INELIGIBLE,
    ERR_INVALID_DEDUCTIONS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PERIOD_OVERLAP,
    ERR_RUN_EMPTY,
    ERR_RUN_HAS_POSTED_EVENTS,
    ERR_STALE_VERSION,
    fail,
)
from middleware import (
    ALL_ROLES,
    ROLE_SPECIALIST,
    authorize,
    get_body,
    opt_number,
    pagination,
    public,
    req_date,
    req_int,
    req_str,
    sort_created,
)
from response import list_response, object_response
from services import audit
from services.waterfall import run_statement_waterfall
from util import new_uuid, parse_date, render_instant

bp = Blueprint("payroll_runs", __name__)


def get_run_or_404(run_id):
    run = store.runs.get(run_id)
    if run is None:
        fail(ERR_NOT_FOUND, 404, "PayrollRun '%s' does not exist." % run_id)
    return run


def get_statement_or_404(statement_id):
    statement = store.statements.get(statement_id)
    if statement is None:
        fail(ERR_NOT_FOUND, 404, "PayStatement '%s' does not exist." % statement_id)
    return statement


@bp.post("/payroll-runs")
def create_run():
    authorize(ROLE_SPECIALIST)
    body = get_body()
    employer_id = req_str(body, "employer_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    pay_date = req_date(body, "pay_date")
    expected_employer_version = req_int(body, "expected_employer_version")

    employer = store.employers.get(employer_id)
    if employer is None:
        fail(ERR_NOT_FOUND, 404, "Employer '%s' does not exist." % employer_id)

    # Temporal window checks: internally sound, externally disjoint.
    if parse_date(period_end) < parse_date(period_start):
        fail(ERR_PERIOD_OVERLAP, 409,
             "period_end must be on or after period_start.")
    previous_ends = [
        parse_date(r["period_end"])
        for r in store.runs.values()
        if r["employer_id"] == employer_id and r["status"] != "VOIDED"
    ]
    if previous_ends:
        latest_end = max(previous_ends)
        if parse_date(period_start) <= latest_end:
            fail(ERR_PERIOD_OVERLAP, 409,
                 "period_start must be strictly after the latest non-voided "
                 "run's period_end (%s)." % latest_end.isoformat())

    # OCC (§2.7).
    if expected_employer_version != employer["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_employer_version %s does not match current employer "
             "version %s." % (expected_employer_version, employer["version"]))

    now = render_instant(logical_now())
    run = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "employer_id": employer_id,
        "period_start": period_start,
        "period_end": period_end,
        "pay_date": pay_date,
        "status": "OPEN",
        "_seq": next_seq(),
    }
    store.runs[run["id"]] = run
    audit.append_audit(employer_id, "PayrollRun", run["id"], "run.create",
                       details={"period_start": period_start,
                                "period_end": period_end,
                                "pay_date": pay_date})
    return object_response(public(run), 201)


@bp.get("/payroll-runs/<runId>")
def get_run(runId):
    authorize(*ALL_ROLES)
    return object_response(public(get_run_or_404(runId)))


@bp.post("/payroll-runs/<runId>/statements")
def create_statement(runId):
    authorize(ROLE_SPECIALIST)
    run = get_run_or_404(runId)
    body = get_body()
    employee_id = req_str(body, "employee_id")
    gross_earnings_cents = req_int(body, "gross_earnings_cents")
    mandatory_deductions_cents = req_int(body, "mandatory_deductions_cents")
    hours_worked = opt_number(body, "hours_worked")

    if run["status"] != "OPEN":
        fail(ERR_INVALID_STATE, 409,
             "Statements may only be added to an OPEN run; current state is %s."
             % run["status"])

    employee = store.employees.get(employee_id)
    if employee is None or employee["employer_id"] != run["employer_id"]:
        fail(ERR_NOT_FOUND, 404,
             "Employee '%s' does not exist within the employer scope."
             % employee_id)

    # Temporal: the TX hourly floor test consumes hours_worked.
    if employee["work_state_code"] == "TX":
        if hours_worked is None or hours_worked <= 0:
            fail(ERR_PERIOD_OVERLAP, 409,
                 "hours_worked is required and must be > 0 for TX employees.")

    # Fiscal bounds: gross > 0; 0 <= mandatory_deductions < gross.
    if gross_earnings_cents <= 0 or mandatory_deductions_cents < 0 \
            or mandatory_deductions_cents >= gross_earnings_cents:
        fail(ERR_INVALID_DEDUCTIONS, 422,
             "mandatory_deductions_cents must be >= 0 and strictly less than "
             "gross_earnings_cents, and gross_earnings_cents must be > 0.")

    # Terminated-employee ineligibility.
    if employee["termination_date"] is not None:
        fail(ERR_EMPLOYEE_TERMINATED_INELIGIBLE, 409,
             "Employee '%s' is terminated; no statements may be created."
             % employee["id"])

    # One statement per employee per run.
    if any(s["payroll_run_id"] == run["id"] and s["employee_id"] == employee_id
           for s in store.statements.values()):
        fail(ERR_INVALID_REQUEST, 400,
             "A statement for employee '%s' already exists in this run."
             % employee_id)

    now = render_instant(logical_now())
    disposable = gross_earnings_cents - mandatory_deductions_cents
    statement = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "payroll_run_id": run["id"],
        "employer_id": run["employer_id"],
        "employee_id": employee_id,
        "gross_earnings_cents": gross_earnings_cents,
        "mandatory_deductions_cents": mandatory_deductions_cents,
        "hours_worked": hours_worked,
        "disposable_earnings_cents": disposable,
        "total_withheld_cents": 0,
        "total_admin_fee_cents": 0,
        "net_pay_cents": disposable,
        "computation_breakdown": [],
        "_seq": next_seq(),
    }
    store.statements[statement["id"]] = statement
    audit.append_audit(run["employer_id"], "PayStatement", statement["id"],
                       "statement.create",
                       details={"payroll_run_id": run["id"],
                                "employee_id": employee_id,
                                "gross_earnings_cents": gross_earnings_cents,
                                "mandatory_deductions_cents": mandatory_deductions_cents})
    return object_response(public(statement), 201)


@bp.get("/payroll-runs/<runId>/statements")
def list_run_statements(runId):
    authorize(*ALL_ROLES)
    get_run_or_404(runId)
    limit, offset = pagination()
    items = sort_created(
        [s for s in store.statements.values() if s["payroll_run_id"] == runId]
    )
    page = items[offset:offset + limit]
    return list_response([public(s) for s in page], len(items), limit, offset)


@bp.get("/statements/<statementId>")
def get_statement(statementId):
    authorize(*ALL_ROLES)
    return object_response(public(get_statement_or_404(statementId)))


@bp.get("/statements/<statementId>/events")
def list_statement_events(statementId):
    authorize(*ALL_ROLES)
    get_statement_or_404(statementId)
    limit, offset = pagination()
    items = sort_created(
        [e for e in store.events.values() if e["pay_statement_id"] == statementId]
    )
    page = items[offset:offset + limit]
    return list_response([public(e) for e in page], len(items), limit, offset)


@bp.post("/payroll-runs/<runId>/pay")
def pay_run(runId):
    authorize(ROLE_SPECIALIST)
    run = get_run_or_404(runId)
    body = get_body()
    expected_employer_version = req_int(body, "expected_employer_version")

    if run["status"] != "OPEN":
        fail(ERR_INVALID_STATE, 409,
             "Only an OPEN run can be paid; current state is %s." % run["status"])

    employer = store.employers[run["employer_id"]]
    # OCC (§2.7) — surfaces before the fiscal empty-run check.
    if expected_employer_version != employer["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_employer_version %s does not match current employer "
             "version %s." % (expected_employer_version, employer["version"]))

    statements = sort_created(
        [s for s in store.statements.values() if s["payroll_run_id"] == run["id"]]
    )
    if not statements:
        fail(ERR_RUN_EMPTY, 422, "Run '%s' has no pay statements." % run["id"])

    # The withholding waterfall runs independently per statement; all cascades
    # complete atomically inside this request.
    for statement in statements:
        employee = store.employees[statement["employee_id"]]
        run_statement_waterfall(statement, run, employee, employer,
                                g.user_role, g.user_id)
        audit.append_audit(run["employer_id"], "PayStatement", statement["id"],
                           "run.pay",
                           details={"payroll_run_id": run["id"],
                                    "employee_id": employee["id"],
                                    "total_withheld_cents": statement["total_withheld_cents"],
                                    "total_admin_fee_cents": statement["total_admin_fee_cents"],
                                    "net_pay_cents": statement["net_pay_cents"]})

    run["status"] = "PAID"
    run["version"] += 1
    run["updated_at"] = render_instant(logical_now())
    store.run_payers[run["id"]] = g.user_id

    # Cascade: Employer.version += 1. Remittances are NOT auto-created.
    employer["version"] += 1
    employer["updated_at"] = render_instant(logical_now())
    return object_response(public(run))


@bp.post("/payroll-runs/<runId>/void")
def void_run(runId):
    authorize(ROLE_SPECIALIST)
    run = get_run_or_404(runId)
    if run["status"] != "OPEN":
        fail(ERR_INVALID_STATE, 409,
             "Only an OPEN run can be voided; current state is %s." % run["status"])

    posted = any(
        e["payroll_run_id"] == run["id"] and e["event_type"] == "WITHHOLD"
        for e in store.events.values()
    )
    if posted:
        fail(ERR_RUN_HAS_POSTED_EVENTS, 409,
             "Run '%s' has posted WITHHOLD events and cannot be voided." % run["id"])

    run["status"] = "VOIDED"
    run["version"] += 1
    run["updated_at"] = render_instant(logical_now())
    employer = store.employers[run["employer_id"]]
    employer["version"] += 1
    employer["updated_at"] = run["updated_at"]
    audit.append_audit(run["employer_id"], "PayrollRun", run["id"], "run.void")
    return object_response(public(run))


@bp.get("/payroll-runs/<runId>/events")
def list_run_events(runId):
    authorize(*ALL_ROLES)
    get_run_or_404(runId)
    limit, offset = pagination()
    items = sort_created(
        [e for e in store.events.values() if e["payroll_run_id"] == runId]
    )
    page = items[offset:offset + limit]
    return list_response([public(e) for e in page], len(items), limit, offset)
