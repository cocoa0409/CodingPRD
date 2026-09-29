"""Benefit accounts and the append-only benefit dollar ledger."""

from flask import Blueprint

import serialize
from auth import (
    authenticate,
    require_employee_scope,
    resolve_account,
    resolve_category,
    resolve_employee,
    resolve_entry,
)
from calc import account_ledger, post_entry, recompute_available, resolve_account_for
from errors import invalid_request
from guards import require_category_active
from responses import array_response, created_response, object_response, paginate
from store import sorted_rows, stamp_new, store
from validate import (
    ENTRY_TYPES,
    SOURCE_ENTITIES,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("accounts", __name__)


@bp.post("/benefits/benefit-accounts")
def create_account():
    authenticate(["ProgramAdmin"])
    specs = [
        field("employee_id", "id", required=True),
        field("benefit_category_id", "id", required=True),
        field("opening_rollover_cents", "integer", default=0, minimum=0),
    ]
    _body, values = parse_body(specs)
    employee = resolve_employee(values["employee_id"])
    category = resolve_category(values["benefit_category_id"])
    require_category_active(category)
    if resolve_account_for(employee["id"], category["id"]) is not None:
        invalid_request("A benefit account already exists for this employee and "
                        "benefit category pair.")
    opening = values["opening_rollover_cents"]
    row = {
        "employee_id": employee["id"],
        "benefit_category_id": category["id"],
        "rollover_in_cents": opening,
        "contributed_cents": 0,
        "spent_cents": 0,
        "forfeited_cents": 0,
        "refunded_cents": 0,
        "reversed_cents": 0,
        "fee_charged_cents": 0,
        "available_balance_cents": 0,
    }
    stamp_new(row)
    store.benefit_accounts[row["id"]] = row
    recompute_available(row)
    if opening > 0:
        post_entry(row, "ROLLOVER_IN", opening, "BenefitAccount", row["id"],
                   "Opening carried-in benefit balance credited at account creation.")
    return created_response(serialize.benefit_account(row))


@bp.get("/benefits/benefit-accounts/<account_id>")
def read_account(account_id):
    principal = authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer"])
    row = resolve_account(account_id)
    require_employee_scope(principal, row["employee_id"])
    return object_response(serialize.benefit_account(row))


@bp.get("/benefits/benefit-accounts")
def list_accounts():
    authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer"])
    employee_id = str_filter("employee_id")
    category_id = str_filter("benefit_category_id")
    limit, offset = pagination()
    rows = []
    for row in store.benefit_accounts.values():
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if category_id is not None and row["benefit_category_id"] != category_id:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.benefit_account(r) for r in page],
                          limit, offset, total)


@bp.get("/benefits/benefit-accounts/<account_id>/ledger-entries")
def list_account_ledger(account_id):
    principal = authenticate(["ProgramAdmin", "Employee", "ComplianceReviewer"])
    row = resolve_account(account_id)
    require_employee_scope(principal, row["employee_id"])
    entry_type = enum_filter("entry_type", ENTRY_TYPES)
    limit, offset = pagination()
    rows = [e for e in account_ledger(row["id"])
            if entry_type is None or e["entry_type"] == entry_type]
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.ledger_entry(r) for r in page],
                          limit, offset, total)


@bp.get("/benefits/ledger-entries/<entry_id>")
def read_entry(entry_id):
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    row = resolve_entry(entry_id)
    return object_response(serialize.ledger_entry(row))


@bp.get("/benefits/ledger-entries")
def list_entries():
    authenticate(["ProgramAdmin", "ComplianceReviewer"])
    account_id = str_filter("benefit_account_id")
    entry_type = enum_filter("entry_type", ENTRY_TYPES)
    source_entity = enum_filter("source_entity", SOURCE_ENTITIES)
    source_id = str_filter("source_id")
    limit, offset = pagination()
    rows = []
    for row in store.ledger_entries.values():
        if account_id is not None and row["benefit_account_id"] != account_id:
            continue
        if entry_type is not None and row["entry_type"] != entry_type:
            continue
        if source_entity is not None and row["source_entity"] != source_entity:
            continue
        if source_id is not None and row["source_id"] != source_id:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.ledger_entry(r) for r in page],
                          limit, offset, total)
