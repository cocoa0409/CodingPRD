"""The vintage-dated fund ledger: reads and refunds (PRD 3.9)."""

from flask import Blueprint, g

import db
import helpers
import response
import serializers
from errors import raise_error
from middleware import ANY, guard
from services import derive, ledger

bp = Blueprint("fund", __name__)

REFUNDABLE_STATUSES = ("REFUND_DUE", "OPEN")


@bp.get("/fund-ledger-entries")
@guard(*ANY)
def list_ledger_entries():
    filters = {
        "facility_category_id": helpers.arg_string("facility_category_id"),
        "development_application_id": helpers.arg_string("development_application_id"),
        "refunded_entry_id": helpers.arg_string("refunded_entry_id"),
        "kind": helpers.arg_enum("kind", helpers.LEDGER_KINDS),
        "entry_status": helpers.arg_enum("entry_status", helpers.ENTRY_STATUSES),
    }
    rows = sorted(
        (entry for entry in db.fund_ledger_entries.values() if helpers.matches(entry, filters)),
        key=derive.fifo_key,
    )
    return response.paginated(rows, serializers.fund_ledger_entry)


@bp.get("/fund-ledger-entries/<entry_id>")
@guard(*ANY)
def read_ledger_entry(entry_id):
    entry = helpers.get_entry(entry_id)
    return response.object_response(serializers.fund_ledger_entry(entry))


@bp.post("/fund-ledger-entries/<entry_id>/refund")
@guard("FinanceOfficer")
def refund_ledger_entry(entry_id):
    entry = helpers.get_entry(entry_id)
    body = helpers.json_body()
    body.forbid_versions()
    body.string("reason", max_len=500)

    if entry["kind"] != "COLLECTION" or entry["entry_status"] not in REFUNDABLE_STATUSES:
        raise_error("ERR_LEDGER_ENTRY_INVALID_STATE")
    if entry["entry_status"] == "OPEN" and ledger.refund_amount(entry) <= 0:
        raise_error("ERR_REFUND_NOT_ELIGIBLE")

    row = ledger.record_refund(entry, g.user_id)
    return response.object_response(serializers.fund_ledger_entry(row), 201)
