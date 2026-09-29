"""Read-only access to the append-only reserve ledger (PRD 2.11, 3.10)."""
from flask import Blueprint, request

from auth import (ACCESS_BILLING_ANALYST, PLATFORM_ADMIN,
                  REVENUE_ASSURANCE_CONTROLLER, authenticate)
from envelope import object_response, paginate
from lookup import get_ledger_entry
from store import db, ordered

bp = Blueprint("ledger", __name__)

READERS = (PLATFORM_ADMIN, REVENUE_ASSURANCE_CONTROLLER, ACCESS_BILLING_ANALYST)


@bp.get("/reserve-ledger-entries/<entry_id>")
def read_entry(entry_id):
    authenticate(READERS)
    return object_response(get_ledger_entry(entry_id))


@bp.get("/reserve-ledger-entries")
def list_entries():
    authenticate(READERS)
    rows = ordered(db.ledger_entries)
    for param in ("carrier_id", "invoice_id", "reserve_bucket", "entry_type"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return paginate(rows, request.args, lambda r: r)
