"""Payroll deduction files: the charge rollup, transmission and acknowledgement."""

from flask import Blueprint

import serialize
from auth import authenticate, resolve_employer, resolve_file
from calc import payroll_rollup
from guards import TERMINAL_PAYROLL_FILE, require_not_terminal, require_transition
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    ACK_OUTCOMES,
    PAYROLL_FILE_STATUSES,
    enum_filter,
    field,
    month_filter,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("payroll", __name__)

GENERATABLE_WINDOW_STATUSES = ("LOCKED", "CLOSED")


@bp.post("/benefits/payroll-files")
def create_payroll_file():
    authenticate(["ProgramAdmin", "PayrollProcessor"])
    specs = [
        field("employer_id", "id", required=True),
        field("period_month", "month", required=True),
    ]
    _body, values = parse_body(specs)
    employer = resolve_employer(values["employer_id"])
    row = {
        "employer_id": employer["id"],
        "period_month": values["period_month"],
        "status": "DRAFT",
        "participant_count": 0,
        "total_pretax_cents": 0,
        "total_posttax_cents": 0,
        "admin_fee_cents": 0,
        "pre_waiver_charge_cents": 0,
        "fee_waiver_cents": 0,
        "employer_charge_cents": 0,
        "transmitted_at": None,
        "acknowledgement_code": None,
    }
    stamp_new(row)
    store.payroll_files[row["id"]] = row
    return created_response(serialize.payroll_file(row))


@bp.get("/benefits/payroll-files/<file_id>")
def read_payroll_file(file_id):
    authenticate(["ProgramAdmin", "PayrollProcessor"])
    row = resolve_file(file_id)
    return object_response(serialize.payroll_file(row))


@bp.get("/benefits/payroll-files")
def list_payroll_files():
    authenticate(["ProgramAdmin", "PayrollProcessor"])
    employer_id = str_filter("employer_id")
    status = enum_filter("status", PAYROLL_FILE_STATUSES)
    period_month = month_filter("period_month")
    limit, offset = pagination()
    rows = []
    for row in store.payroll_files.values():
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if period_month is not None and row["period_month"] != period_month:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.payroll_file(r) for r in page],
                         limit, offset, total)


@bp.post("/benefits/payroll-files/<file_id>/generate")
def generate_payroll_file(file_id):
    authenticate(["ProgramAdmin", "PayrollProcessor"])
    row = resolve_file(file_id)
    require_not_terminal(row, "status", TERMINAL_PAYROLL_FILE, "PayrollFile")
    require_transition(row["status"] == "DRAFT",
                       "PayrollFile %s cannot be generated from status %s."
                       % (row["id"], row["status"]))
    has_window = False
    for window in store.election_windows.values():
        if window["employer_id"] != row["employer_id"]:
            continue
        if window["benefit_month"] != row["period_month"]:
            continue
        if window["status"] in GENERATABLE_WINDOW_STATUSES:
            has_window = True
            break
    require_transition(has_window,
                       "PayrollFile %s cannot be generated because the employer has "
                       "no LOCKED or CLOSED election window for %s."
                       % (row["id"], row["period_month"]))
    payroll_rollup(row)
    row["status"] = "GENERATED"
    bump(row)
    return object_response(serialize.payroll_file(row))


@bp.post("/benefits/payroll-files/<file_id>/transmit")
def transmit_payroll_file(file_id):
    authenticate(["PayrollProcessor"])
    row = resolve_file(file_id)
    require_not_terminal(row, "status", TERMINAL_PAYROLL_FILE, "PayrollFile")
    require_transition(row["status"] == "GENERATED",
                       "PayrollFile %s cannot be transmitted from status %s."
                       % (row["id"], row["status"]))
    require_transition(row["participant_count"] >= 1,
                       "PayrollFile %s carries no participants and cannot be "
                       "transmitted." % row["id"])
    row["status"] = "TRANSMITTED"
    row["transmitted_at"] = store.clock_iso()
    bump(row)
    return object_response(serialize.payroll_file(row))


@bp.post("/benefits/payroll-files/<file_id>/acknowledge")
def acknowledge_payroll_file(file_id):
    authenticate(["PayrollProcessor"])
    row = resolve_file(file_id)
    specs = [
        field("outcome", "enum", required=True, choices=ACK_OUTCOMES),
        field("acknowledgement_code", "string", default=None, nullable=True),
    ]
    _body, values = parse_body(specs)
    require_not_terminal(row, "status", TERMINAL_PAYROLL_FILE, "PayrollFile")
    require_transition(row["status"] == "TRANSMITTED",
                       "PayrollFile %s cannot be acknowledged from status %s."
                       % (row["id"], row["status"]))
    row["status"] = "ACKNOWLEDGED" if values["outcome"] == "ACCEPTED" else "REJECTED"
    row["acknowledgement_code"] = values["acknowledgement_code"]
    bump(row)
    return object_response(serialize.payroll_file(row))
