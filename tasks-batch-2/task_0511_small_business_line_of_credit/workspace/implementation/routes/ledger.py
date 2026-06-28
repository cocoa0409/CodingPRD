"""LedgerEntry read-only routes (PRD §2.8, §3.8). Listable/fetchable only;
never created directly by a client."""
from flask import Blueprint, request

import db
import serialize
from common import list_response
from lookups import get_credit_line, get_ledger_entry
from middleware import auth_and_role
from response import object_response

bp = Blueprint("ledger", __name__)


@bp.get("/credit-lines/<rid>/ledger-entries")
def list_for_line(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    entry_type = request.args.get("entry_type")
    items = [e for e in db.ledger_entries.values() if e["credit_line_id"] == rid]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return list_response(items, serialize.ledger_entry)


@bp.get("/ledger-entries")
def list_all():
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    credit_line_id = request.args.get("credit_line_id")
    draw_id = request.args.get("draw_id")
    remittance_id = request.args.get("remittance_id")
    entry_type = request.args.get("entry_type")
    items = list(db.ledger_entries.values())
    if credit_line_id is not None:
        items = [e for e in items if e["credit_line_id"] == credit_line_id]
    if draw_id is not None:
        items = [e for e in items if e["draw_id"] == draw_id]
    if remittance_id is not None:
        items = [e for e in items if e["remittance_id"] == remittance_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    return list_response(items, serialize.ledger_entry)


@bp.get("/ledger-entries/<rid>")
def fetch_entry(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    e = get_ledger_entry(rid)
    return object_response(serialize.ledger_entry(e), 200)
