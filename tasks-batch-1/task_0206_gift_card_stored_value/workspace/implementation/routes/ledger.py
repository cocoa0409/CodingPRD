"""LedgerEntry read/list (PRD §2.4)."""

from flask import Blueprint, request

from db import db
from core import paginate
from middleware import get_identity, require_role
from response import success
from lookups import get_ledger_entry
import serialize

bp = Blueprint("ledger", __name__)

_READ_ROLES = {"StoreAssociate", "ProgramAdmin", "FraudAnalyst", "Customer"}


@bp.get("/v1/ledger-entries/<ledger_entry_id>")
def read_entry(ledger_entry_id):
    _uid, role = get_identity()
    require_role(role, _READ_ROLES)
    e = get_ledger_entry(ledger_entry_id)
    return success(serialize.ledger_entry(e))


@bp.get("/v1/ledger-entries")
def list_entries():
    _uid, role = get_identity()
    require_role(role, _READ_ROLES)
    items = list(db.ledger_entries.values())
    for key in ("card_id", "program_id", "entry_type", "reverses_entry_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    page, pg = paginate(items)
    return success([serialize.ledger_entry(e) for e in page], pagination=pg)
