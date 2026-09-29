"""Corrected wage statements and the reissue chain (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_EMPLOYEE, R_PREPARER, READ6, READ7, STATE_RE,
    authenticate, db, fail, get_case, get_employee, get_statement, get_body, matches,
    new_row, now, ok, pagination, paginate, qs, qs_bool, qs_int, require_state,
    sorted_rows, tax_year_field, touch, validate,
)
from serializers import statement_json

bp = Blueprint("statements", __name__)

# VOIDED is the only terminal statement state; ACKNOWLEDGED still answers
# ERR_INVALID_STATE because the repayment-collection cascade can still void it.
TERMINAL = ("VOIDED",)

STATEMENT_CREATE = {
    "correction_case_id": F("string", True),
    "employee_id": F("string", True),
    "tax_year": tax_year_field(True),
    "delivery_channel": F("string", True, enum=("MAIL", "PORTAL")),
    "supersedes_statement_id": F("string", False),
}


def _case_of(statement):
    return db.correction_cases.get(statement["correction_case_id"])


def _statement_employer(statement):
    case = _case_of(statement)
    return case["employer_id"] if case else None


def _prior_year_window_open(tax_year):
    """A statement more than three calendar years old is out of reach entirely."""
    return tax_year >= now().year - 3


def _next_sequence_no(case_id, employee_id):
    return 1 + sum(1 for s in db.statements.values()
                   if s["correction_case_id"] == case_id and s["employee_id"] == employee_id)


@bp.post("/corrected-wage-statements")
def create_statement():
    authenticate((R_ADMIN, R_PREPARER))
    body = get_body()
    case = None
    employee = None
    if isinstance(body.get("correction_case_id"), str) and body["correction_case_id"]:
        case = get_case(body["correction_case_id"])
    if isinstance(body.get("employee_id"), str) and body["employee_id"]:
        employee = get_employee(body["employee_id"])
    if isinstance(body.get("supersedes_statement_id"), str) and body["supersedes_statement_id"]:
        get_statement(body["supersedes_statement_id"])
    data = validate(body, STATEMENT_CREATE)

    if employee["employer_id"] != case["employer_id"]:
        fail("ERR_SCOPE_MISMATCH", "the employee does not belong to the case's employer")
    if not _prior_year_window_open(data["tax_year"]):
        fail("ERR_PRIOR_YEAR_WINDOW_CLOSED",
             "the statement's tax year is more than three years before the current year")

    row = new_row({
        "correction_case_id": case["id"],
        "employee_id": employee["id"],
        "supersedes_statement_id": data.get("supersedes_statement_id"),
        "tax_year": data["tax_year"],
        "is_prior_year": data["tax_year"] < now().year,
        "sequence_no": _next_sequence_no(case["id"], employee["id"]),
        "wage_delta_cents": 0,
        "fica_wage_delta_cents": 0,
        "withholding_delta_cents": 0,
        "delivery_channel": data["delivery_channel"],
        "status": "DRAFT",
        "issued_at": None,
        "acknowledged_at": None,
        "undeliverable_reason": None,
    })
    wage, fica, withholding = calc.compute_box_deltas(row)
    if wage == 0 and fica == 0 and withholding == 0:
        fail("ERR_NO_REPORTABLE_DELTA",
             "the computed box deltas are all zero; there is nothing to report")
    row["wage_delta_cents"] = wage
    row["fica_wage_delta_cents"] = fica
    row["withholding_delta_cents"] = withholding
    db.statements[row["id"]] = row
    return ok(statement_json(row), 201)


@bp.get("/corrected-wage-statements/<statement_id>")
def read_statement(statement_id):
    actor = authenticate(READ7)
    row = get_statement(statement_id)
    actor.require_employer(_statement_employer(row))
    actor.require_employee(row["employee_id"])
    return ok(statement_json(row))


@bp.get("/corrected-wage-statements")
def list_statements():
    actor = authenticate(READ7)
    limit, offset = pagination()
    filters = {
        "correction_case_id": qs("correction_case_id"),
        "employee_id": actor.scoped_employee(qs("employee_id")),
        "supersedes_statement_id": qs("supersedes_statement_id"),
        "tax_year": qs_int("tax_year"),
        "delivery_channel": qs("delivery_channel"),
        "is_prior_year": qs_bool("is_prior_year"),
        "status": qs("status"),
    }
    rows = [r for r in sorted_rows(db.statements.values()) if matches(r, filters)]
    if actor.role == "EmployerRep":
        rows = [r for r in rows if _statement_employer(r) == actor.user_id]
    return paginate(rows, limit, offset, statement_json)


def _advance_case_to_issued(case):
    if case["statement_status"] in ("STMT_PENDING", "STMT_REISSUE_PENDING"):
        case["statement_status"] = "STMT_ISSUED"
        return True
    return False


@bp.post("/corrected-wage-statements/<statement_id>/issue")
def issue_statement(statement_id):
    authenticate((R_ADMIN, R_PREPARER))
    statement = get_statement(statement_id)
    get_body()
    case = _case_of(statement)
    employee = db.employees.get(statement["employee_id"])
    agency = db.tax_agencies.get(case["agency_id"]) if case else None

    require_state(statement["status"], ("DRAFT",), TERMINAL)

    for rep in calc.case_repayments(case["id"]):
        if rep["status"] not in calc.SETTLED_REPAYMENT_STATES:
            fail("ERR_REPAYMENT_NOT_SETTLED",
                 "an unsettled wage repayment can still change the box deltas")

    if not _prior_year_window_open(statement["tax_year"]):
        fail("ERR_PRIOR_YEAR_WINDOW_CLOSED",
             "the statement's tax year is more than three years before the current year")
    if statement["is_prior_year"]:
        filed = calc.case_filed_return(case)
        if filed is not None and agency is not None:
            boundary = filed["original_due_date"] + timedelta(days=agency["amendment_window_days"])
            if now() > boundary:
                fail("ERR_PRIOR_YEAR_WINDOW_CLOSED",
                     "the prior-year statement window has closed")

    wage, fica, withholding = calc.compute_box_deltas(statement)
    if wage == 0 and fica == 0 and withholding == 0:
        fail("ERR_NO_REPORTABLE_DELTA",
             "the recomputed box deltas are all zero; there is nothing to issue")

    statement["wage_delta_cents"] = wage
    statement["fica_wage_delta_cents"] = fica
    statement["withholding_delta_cents"] = withholding
    statement["status"] = "ISSUED"
    statement["issued_at"] = now()
    touch(statement)

    moved = _advance_case_to_issued(case)
    if moved:
        # statement_status reaching STMT_ISSUED can complete the compound join
        # OPEN -> REMEDIATION_PENDING when the filing dimension already allows it.
        calc.join_remediation_pending(case)
    calc.sync_employee(employee)
    calc.sync_case(case, forced=moved)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(statement_json(statement))


@bp.post("/corrected-wage-statements/<statement_id>/acknowledge")
def acknowledge_statement(statement_id):
    actor = authenticate((R_ADMIN, R_EMPLOYEE))
    statement = get_statement(statement_id)
    get_body()
    actor.require_employee(statement["employee_id"])
    case = _case_of(statement)
    employee = db.employees.get(statement["employee_id"])

    require_state(statement["status"], ("ISSUED",), TERMINAL)

    statement["status"] = "ACKNOWLEDGED"
    statement["acknowledged_at"] = now()
    touch(statement)

    outstanding = sum(1 for s in calc.case_statements(case["id"])
                      if s["status"] in calc.OUTSTANDING_STATEMENT_STATES)
    moved = False
    if outstanding == 0 and case["statement_status"] == "STMT_ISSUED":
        case["statement_status"] = "STMT_COMPLETE"
        moved = True
        calc.join_remediation_pending(case)
    calc.sync_employee(employee)
    calc.sync_case(case, forced=moved)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(statement_json(statement))


@bp.post("/corrected-wage-statements/<statement_id>/report-undeliverable")
def report_undeliverable(statement_id):
    authenticate((R_ADMIN, R_PREPARER))
    statement = get_statement(statement_id)
    body = get_body()
    data = validate(body, {"undeliverable_reason": F("string", True, min_len=1, max_len=2000)})
    case = _case_of(statement)
    employee = db.employees.get(statement["employee_id"])

    require_state(statement["status"], ("ISSUED",), TERMINAL)
    if statement["delivery_channel"] != "MAIL":
        fail("ERR_CHANNEL_NOT_UNDELIVERABLE_CAPABLE",
             "only a MAIL statement can be reported undeliverable")

    statement["status"] = "RETURNED_UNDELIVERABLE"
    statement["undeliverable_reason"] = data["undeliverable_reason"]
    touch(statement)

    calc.sync_employee(employee)
    calc.sync_case(case)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(statement_json(statement))


REISSUE_INPUT = {
    "expected_statement_version": F("integer", True),
    "delivery_channel": F("string", False, enum=("MAIL", "PORTAL")),
    "reissue_reason": F("string", False, min_len=1, max_len=2000),
    "corrected_mailing_state_code": F("string", False, pattern=STATE_RE),
}


def spawn_successor(predecessor, delivery_channel=None):
    """Void nothing; just mint the DRAFT successor with fresh box deltas."""
    row = new_row({
        "correction_case_id": predecessor["correction_case_id"],
        "employee_id": predecessor["employee_id"],
        "supersedes_statement_id": predecessor["id"],
        "tax_year": predecessor["tax_year"],
        "is_prior_year": predecessor["tax_year"] < now().year,
        "sequence_no": predecessor["sequence_no"] + 1,
        "wage_delta_cents": 0,
        "fica_wage_delta_cents": 0,
        "withholding_delta_cents": 0,
        "delivery_channel": delivery_channel or predecessor["delivery_channel"],
        "status": "DRAFT",
        "issued_at": None,
        "acknowledged_at": None,
        "undeliverable_reason": None,
    })
    db.statements[row["id"]] = row
    calc.write_box_deltas(row)
    return row


def reissue_case_dimension(case):
    """STMT_ISSUED -> STMT_REISSUE_PENDING, which can reopen the whole case."""
    moved = False
    if case["statement_status"] == "STMT_ISSUED":
        case["statement_status"] = "STMT_REISSUE_PENDING"
        moved = True
        if case["status"] == "REMEDIATION_PENDING":
            case["status"] = "OPEN"
    return moved


@bp.post("/corrected-wage-statements/<statement_id>/reissue")
def reissue_statement(statement_id):
    authenticate((R_ADMIN, R_PREPARER))
    predecessor = get_statement(statement_id)
    body = get_body()
    data = validate(body, REISSUE_INPUT)
    case = _case_of(predecessor)
    employee = db.employees.get(predecessor["employee_id"])

    if data["expected_statement_version"] != predecessor["version"]:
        fail("ERR_STALE_STATEMENT_VERSION",
             "expected_statement_version does not match the statement's current version")

    require_state(predecessor["status"], ("ISSUED", "RETURNED_UNDELIVERABLE"), TERMINAL)

    predecessor["status"] = "VOIDED"
    touch(predecessor)

    if employee is not None and data.get("corrected_mailing_state_code"):
        employee["mailing_state_code"] = data["corrected_mailing_state_code"]
        touch(employee)

    successor = spawn_successor(predecessor, data.get("delivery_channel"))
    moved = reissue_case_dimension(case)
    calc.sync_employee(employee)
    calc.sync_case(case, forced=moved)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(statement_json(successor), 201)
