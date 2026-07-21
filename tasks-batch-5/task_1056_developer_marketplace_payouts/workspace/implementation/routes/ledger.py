"""Ledger entry reads."""
from flask import Blueprint

from core import (
    authenticate,
    db,
    filter_eq,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
)
from services import lookup

bp = Blueprint("ledger", __name__)


@bp.get("/api/ledger-entries")
def list_entries():
    authenticate({"FinanceOps", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.ledger_entries)
    for field in ("developer_id", "purchase_id", "payout_line_id", "entry_type", "settled"):
        rows = filter_eq(rows, field)
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/ledger-entries/<ledger_entry_id>")
def read_entry(ledger_entry_id):
    authenticate({"FinanceOps", "PlatformAdmin", "Developer"})
    rec = lookup("ledger_entries", ledger_entry_id)
    return ok(public(rec))
