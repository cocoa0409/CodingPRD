"""Wage repayment recovery and its five-link statement cascade (PRD 3.7)."""

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_ANALYST, R_EMPLOYEE, R_OFFICER, READ7,
    authenticate, cents, db, fail, get_case, get_employee, get_repayment, get_body,
    matches, new_row, ok, pagination, paginate, qs, require_state, sorted_rows,
    tax_year_field, touch, validate,
)
from routes.statements import reissue_case_dimension, spawn_successor
from serializers import repayment_json

bp = Blueprint("repayments", __name__)

TERMINAL = ("COLLECTED", "WRITTEN_OFF", "CANCELLED")

REPAYMENT_CREATE = {
    "correction_case_id": F("string", True),
    "employee_id": F("string", True),
    "overpaid_gross_cents": F("integer", True, exclusive_minimum=0),
    "overpaid_income_tax_withheld_cents": cents(True),
    "overpaid_fica_withheld_cents": cents(True),
    "overpayment_tax_year": tax_year_field(True),
    "recovery_tax_year": tax_year_field(True),
    "installment_count": F("integer", False, minimum=1, maximum=24),
}

RENEGOTIATE_INPUT = {
    "overpaid_gross_cents": F("integer", False, exclusive_minimum=0),
    "overpaid_income_tax_withheld_cents": cents(False),
    "overpaid_fica_withheld_cents": cents(False),
    "recovery_tax_year": tax_year_field(False),
    "installment_count": F("integer", False, minimum=1, maximum=24),
}


def _case_of(repayment):
    return db.correction_cases.get(repayment["correction_case_id"])


def _repayment_employer(repayment):
    case = _case_of(repayment)
    return case["employer_id"] if case else None


def _check_recovery_arithmetic(gross, income_tax, fica, overpayment_year, recovery_year):
    if recovery_year < overpayment_year:
        fail("ERR_INVALID_RECOVERY_YEAR",
             "recovery_tax_year may not be earlier than overpayment_tax_year")
    if income_tax + fica > gross:
        fail("ERR_INVALID_RECOVERY_YEAR",
             "the withheld components may not exceed overpaid_gross_cents")


@bp.post("/wage-repayments")
def create_repayment():
    authenticate((R_ADMIN, R_ANALYST))
    body = get_body()
    case = None
    employee = None
    if isinstance(body.get("correction_case_id"), str) and body["correction_case_id"]:
        case = get_case(body["correction_case_id"])
    if isinstance(body.get("employee_id"), str) and body["employee_id"]:
        employee = get_employee(body["employee_id"])
    data = validate(body, REPAYMENT_CREATE)

    _check_recovery_arithmetic(data["overpaid_gross_cents"],
                              data["overpaid_income_tax_withheld_cents"],
                              data["overpaid_fica_withheld_cents"],
                              data["overpayment_tax_year"],
                              data["recovery_tax_year"])
    if employee["employer_id"] != case["employer_id"]:
        fail("ERR_SCOPE_MISMATCH", "the employee does not belong to the case's employer")

    row = new_row({
        "correction_case_id": case["id"],
        "employee_id": employee["id"],
        "overpaid_gross_cents": data["overpaid_gross_cents"],
        "overpaid_income_tax_withheld_cents": data["overpaid_income_tax_withheld_cents"],
        "overpaid_fica_withheld_cents": data["overpaid_fica_withheld_cents"],
        "overpayment_tax_year": data["overpayment_tax_year"],
        "recovery_tax_year": data["recovery_tax_year"],
        "recovery_basis": None,
        "employee_due_cents": 0,
        "agency_recoverable_cents": 0,
        "installment_count": data.get("installment_count"),
        "collected_cents": 0,
        "status": "PROPOSED",
        "write_off_reason": None,
    })
    calc.apply_recovery_basis(row)
    db.wage_repayments[row["id"]] = row
    return ok(repayment_json(row), 201)


@bp.get("/wage-repayments/<wage_repayment_id>")
def read_repayment(wage_repayment_id):
    actor = authenticate(READ7)
    row = get_repayment(wage_repayment_id)
    actor.require_employer(_repayment_employer(row))
    actor.require_employee(row["employee_id"])
    return ok(repayment_json(row))


@bp.get("/wage-repayments")
def list_repayments():
    actor = authenticate(READ7)
    limit, offset = pagination()
    filters = {
        "correction_case_id": qs("correction_case_id"),
        "employee_id": actor.scoped_employee(qs("employee_id")),
        "recovery_basis": qs("recovery_basis"),
        "status": qs("status"),
    }
    rows = [r for r in sorted_rows(db.wage_repayments.values()) if matches(r, filters)]
    if actor.role == "EmployerRep":
        rows = [r for r in rows if _repayment_employer(r) == actor.user_id]
    return paginate(rows, limit, offset, repayment_json)


@bp.post("/wage-repayments/<wage_repayment_id>/agree")
def agree_repayment(wage_repayment_id):
    actor = authenticate((R_ADMIN, R_ANALYST, R_EMPLOYEE))
    row = get_repayment(wage_repayment_id)
    body = get_body()
    data = validate(body, {"installment_count": F("integer", False, minimum=1, maximum=24)})
    actor.require_employee(row["employee_id"])
    case = _case_of(row)

    require_state(row["status"], ("PROPOSED",), TERMINAL)
    if case is None or case["status"] not in ("OPEN", "REMEDIATION_PENDING"):
        fail("ERR_INVALID_STATE", "a closed case cannot acquire new repayment agreements")

    if "installment_count" in data:
        row["installment_count"] = data["installment_count"]
    row["status"] = "AGREED"
    touch(row)
    return ok(repayment_json(row))


@bp.post("/wage-repayments/<wage_repayment_id>/renegotiate")
def renegotiate_repayment(wage_repayment_id):
    authenticate((R_ADMIN, R_ANALYST))
    row = get_repayment(wage_repayment_id)
    body = get_body()
    data = validate(body, RENEGOTIATE_INPUT)

    gross = data.get("overpaid_gross_cents", row["overpaid_gross_cents"])
    income_tax = data.get("overpaid_income_tax_withheld_cents",
                          row["overpaid_income_tax_withheld_cents"])
    fica = data.get("overpaid_fica_withheld_cents", row["overpaid_fica_withheld_cents"])
    recovery_year = data.get("recovery_tax_year", row["recovery_tax_year"])
    _check_recovery_arithmetic(gross, income_tax, fica,
                               row["overpayment_tax_year"], recovery_year)

    require_state(row["status"], ("AGREED",), TERMINAL)
    if row["collected_cents"] != 0:
        fail("ERR_INVALID_STATE", "terms may not be renegotiated once money has moved")

    row["overpaid_gross_cents"] = gross
    row["overpaid_income_tax_withheld_cents"] = income_tax
    row["overpaid_fica_withheld_cents"] = fica
    row["recovery_tax_year"] = recovery_year
    calc.apply_recovery_basis(row)
    row["installment_count"] = None
    row["status"] = "PROPOSED"
    touch(row)
    return ok(repayment_json(row))


@bp.post("/wage-repayments/<wage_repayment_id>/collect")
def collect_repayment(wage_repayment_id):
    authenticate((R_ADMIN, R_ANALYST))
    row = get_repayment(wage_repayment_id)
    body = get_body()
    data = validate(body, {"collected_cents": cents(True)})
    case = _case_of(row)

    require_state(row["status"], ("AGREED",), TERMINAL)
    if data["collected_cents"] != row["employee_due_cents"]:
        fail("ERR_OVERCOLLECTION",
             "collected_cents must equal employee_due_cents exactly")

    # Link one: the transition plus the recovery rollup.
    row["status"] = "COLLECTED"
    row["collected_cents"] = data["collected_cents"]
    touch(row)

    # Link two: void every counted statement for the overpayment year and respawn it.
    touched_employees = set()
    voided_any = False
    for statement in calc.case_statements(case["id"]):
        if statement["tax_year"] != row["overpayment_tax_year"]:
            continue
        if statement["status"] not in calc.COUNTED_STATEMENT_STATES:
            continue
        statement["status"] = "VOIDED"
        touch(statement)
        spawn_successor(statement)
        touched_employees.add(statement["employee_id"])
        voided_any = True

    # Link three: employee counts and the case wage base.
    for employee_id in sorted(touched_employees):
        calc.sync_employee(db.employees.get(employee_id))

    # Links four and five: the statement dimension flip reopens the case.
    moved = reissue_case_dimension(case) if voided_any else False
    calc.sync_case(case, forced=moved)
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(repayment_json(row))


@bp.post("/wage-repayments/<wage_repayment_id>/write-off")
def write_off_repayment(wage_repayment_id):
    authenticate((R_ADMIN, R_OFFICER))
    row = get_repayment(wage_repayment_id)
    body = get_body()
    data = validate(body, {"write_off_reason": F("string", True, min_len=1, max_len=2000)})

    require_state(row["status"], ("PROPOSED", "AGREED"), TERMINAL)

    row["write_off_reason"] = data["write_off_reason"]
    row["status"] = "CANCELLED" if row["status"] == "PROPOSED" else "WRITTEN_OFF"
    touch(row)
    return ok(repayment_json(row))
