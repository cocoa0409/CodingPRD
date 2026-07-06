"""Ledger entry read routes (PRD §3.7). Append-only; never mutated via API."""
from flask import Blueprint, request

import db
import response
from middleware import (
    get_user_context, require_role, get_pagination,
)
from services import lookup, listing
from services.serialize import ledger_out

bp = Blueprint("ledger", __name__)


@bp.get("/ledger-entries")
def list_ledger():
    _, role = get_user_context()
    require_role(role, {"FinanceController", "AccountManager", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.ledger_entries.values()), {
            "client_id": request.args.get("client_id"),
            "boost_campaign_id": request.args.get("boost_campaign_id"),
            "entry_type": request.args.get("entry_type"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([ledger_out(l) for l in window], limit, offset, total)


@bp.get("/ledger-entries/<entry_id>")
def get_ledger(entry_id):
    _, role = get_user_context()
    require_role(role, {"FinanceController", "AccountManager", "PlatformAdmin"})
    with db.LOCK:
        l = lookup.get_ledger(entry_id)
        return response.ok(ledger_out(l))
