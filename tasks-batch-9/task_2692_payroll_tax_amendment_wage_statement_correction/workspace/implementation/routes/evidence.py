"""Payroll register lines, deposit records and originally filed returns (PRD 3.1)."""

from flask import Blueprint

from common import (
    F, R_ADMIN, R_ANALYST, R_PREPARER, READ6, JURISDICTION_RE,
    authenticate, cents, db, fail, get_agency, get_employee, get_employer,
    get_body, get_deposit, get_filed_return, get_register_line, matches, new_row, ok,
    pagination, paginate, qs, qs_int, quarter_field, sorted_rows,
    statutory_due_date, tax_year_field, validate,
)
from serializers import deposit_json, filed_return_json, register_line_json

bp = Blueprint("evidence", __name__)


# ---------------------------------------------------------------------------
# Payroll register lines (immutable evidence)
# ---------------------------------------------------------------------------

REGISTER_LINE_CREATE = {
    "employer_id": F("string", True),
    "employee_id": F("string", True),
    "agency_id": F("string", True),
    "tax_year": tax_year_field(True),
    "quarter": quarter_field(True),
    "taxable_wage_cents": cents(True),
    "withheld_cents": cents(True),
    "work_jurisdiction_code": F("string", True, pattern=JURISDICTION_RE),
    "workday_ratio_bps": F("integer", False, minimum=0, maximum=10000),
}


@bp.post("/payroll-register-lines")
def create_register_line():
    actor = authenticate((R_ADMIN, R_ANALYST))
    body = get_body()
    employer = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("employee_id"), str) and body["employee_id"]:
        get_employee(body["employee_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    data = validate(body, REGISTER_LINE_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])
    row = new_row({
        "employer_id": data["employer_id"],
        "employee_id": data["employee_id"],
        "agency_id": data["agency_id"],
        "tax_year": data["tax_year"],
        "quarter": data["quarter"],
        "taxable_wage_cents": data["taxable_wage_cents"],
        "withheld_cents": data["withheld_cents"],
        "work_jurisdiction_code": data["work_jurisdiction_code"],
        "workday_ratio_bps": data.get("workday_ratio_bps", 10000),
        "posting_status": "POSTED",
    }, versioned=False)
    db.register_lines[row["id"]] = row
    return ok(register_line_json(row), 201)


@bp.get("/payroll-register-lines/<register_line_id>")
def read_register_line(register_line_id):
    actor = authenticate(READ6)
    row = get_register_line(register_line_id)
    actor.require_employer(row["employer_id"])
    return ok(register_line_json(row))


@bp.get("/payroll-register-lines")
def list_register_lines():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "employee_id": qs("employee_id"),
        "agency_id": qs("agency_id"),
        "tax_year": qs_int("tax_year"),
        "quarter": qs_int("quarter"),
    }
    rows = [r for r in sorted_rows(db.register_lines.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, register_line_json)


# ---------------------------------------------------------------------------
# Deposit records (immutable evidence)
# ---------------------------------------------------------------------------

DEPOSIT_CREATE = {
    "employer_id": F("string", True),
    "agency_id": F("string", True),
    "tax_year": tax_year_field(True),
    "quarter": quarter_field(True),
    "deposit_due_date": F("datetime", True),
    "deposit_date": F("datetime", True),
    "amount_cents": cents(True),
    "obligation_amount_cents": cents(True),
    "clearing_status": F("string", False, enum=("CLEARED", "RETURNED")),
}


@bp.post("/deposit-records")
def create_deposit():
    actor = authenticate((R_ADMIN, R_ANALYST))
    body = get_body()
    employer = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    data = validate(body, DEPOSIT_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])
    row = new_row({
        "employer_id": data["employer_id"],
        "agency_id": data["agency_id"],
        "tax_year": data["tax_year"],
        "quarter": data["quarter"],
        "deposit_due_date": data["deposit_due_date"],
        "deposit_date": data["deposit_date"],
        "amount_cents": data["amount_cents"],
        "obligation_amount_cents": data["obligation_amount_cents"],
        "clearing_status": data.get("clearing_status", "CLEARED"),
    }, versioned=False)
    db.deposit_records[row["id"]] = row
    return ok(deposit_json(row), 201)


@bp.get("/deposit-records/<deposit_record_id>")
def read_deposit(deposit_record_id):
    actor = authenticate(READ6)
    row = get_deposit(deposit_record_id)
    actor.require_employer(row["employer_id"])
    return ok(deposit_json(row))


@bp.get("/deposit-records")
def list_deposits():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "agency_id": qs("agency_id"),
        "tax_year": qs_int("tax_year"),
        "quarter": qs_int("quarter"),
        "clearing_status": qs("clearing_status"),
    }
    rows = [r for r in sorted_rows(db.deposit_records.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, deposit_json)


# ---------------------------------------------------------------------------
# Filed returns
# ---------------------------------------------------------------------------

FILED_RETURN_CREATE = {
    "employer_id": F("string", True),
    "agency_id": F("string", True),
    "tax_year": tax_year_field(True),
    "quarter": quarter_field(True),
    "form_code": F("string", True, min_len=1, max_len=16),
    "filed_at": F("datetime", True),
    "reported_taxable_wage_cents": cents(True),
    "reported_withheld_cents": cents(True),
}


@bp.post("/filed-returns")
def create_filed_return():
    actor = authenticate((R_ADMIN, R_ANALYST, R_PREPARER))
    body = get_body()
    employer = None
    if isinstance(body.get("employer_id"), str) and body["employer_id"]:
        employer = get_employer(body["employer_id"])
    if isinstance(body.get("agency_id"), str) and body["agency_id"]:
        get_agency(body["agency_id"])
    data = validate(body, FILED_RETURN_CREATE)
    if employer is not None:
        actor.require_employer(employer["id"])

    for row in db.filed_returns.values():
        if (row["employer_id"] == data["employer_id"]
                and row["agency_id"] == data["agency_id"]
                and row["tax_year"] == data["tax_year"]
                and row["quarter"] == data["quarter"]
                and row["form_code"] == data["form_code"]):
            fail("ERR_DUPLICATE_FILED_RETURN",
                 "a return already exists for this employer, agency, period and form")

    row = new_row({
        "employer_id": data["employer_id"],
        "agency_id": data["agency_id"],
        "tax_year": data["tax_year"],
        "quarter": data["quarter"],
        "form_code": data["form_code"],
        "filed_at": data["filed_at"],
        "reported_taxable_wage_cents": data["reported_taxable_wage_cents"],
        "reported_withheld_cents": data["reported_withheld_cents"],
        "original_due_date": statutory_due_date(data["tax_year"], data["quarter"]),
        "status": "FILED",
    })
    db.filed_returns[row["id"]] = row
    return ok(filed_return_json(row), 201)


@bp.get("/filed-returns/<filed_return_id>")
def read_filed_return(filed_return_id):
    actor = authenticate(READ6)
    row = get_filed_return(filed_return_id)
    actor.require_employer(row["employer_id"])
    return ok(filed_return_json(row))


@bp.get("/filed-returns")
def list_filed_returns():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "employer_id": actor.scoped_employer(qs("employer_id")),
        "agency_id": qs("agency_id"),
        "tax_year": qs_int("tax_year"),
        "quarter": qs_int("quarter"),
        "status": qs("status"),
    }
    rows = [r for r in sorted_rows(db.filed_returns.values()) if matches(r, filters)]
    return paginate(rows, limit, offset, filed_return_json)
