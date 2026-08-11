"""Append-only audit ledger reads (PRD §2.8, §3.9)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from models import ledger_view
from response import list_response, ok_object

bp = Blueprint("ledger", __name__)


@bp.get("/registry/ledger-entries")
@require_roles("Registrar", "Admin")
def list_ledger_entries():
    recs = list(db.ledger.values())
    for param in ("owner_id", "partner_org_id", "auction_id", "bicycle_id", "entry_type"):
        value = request.args.get(param)
        if value is not None:
            recs = [e for e in recs if e[param] == value]
    return list_response(recs, ledger_view)


@bp.get("/registry/ledger-entries/<entry_id>")
@require_roles("Registrar", "Admin")
def read_ledger_entry(entry_id):
    rec = db.ledger.get(entry_id)
    if rec is None:
        # The PRD catalog declares no ledger-specific 404 id; keep HTTP 404.
        raise ApiError("ERR_INVALID_REQUEST", 404, "Ledger entry not found")
    return ok_object(ledger_view(rec))
