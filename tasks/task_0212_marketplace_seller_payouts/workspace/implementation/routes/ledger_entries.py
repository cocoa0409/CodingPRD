"""Ledger entry read endpoints (PRD §2.6, §2.8 reverse-reachability)."""
from flask import Blueprint, request

from common import parse_pagination, paginate, sort_by_created
from db import db
from middleware import (
    get_identity, require_roles, ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE,
)
from response import success
from routes.helpers import fetch, ensure_seller_owns

bp = Blueprint("ledger_entries", __name__)


@bp.get("/ledger-entries/<entry_id>")
def get_ledger_entry(entry_id):
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    entry = fetch(db.ledger_entries, entry_id)
    ensure_seller_owns(role, user_id, entry["seller_id"])
    return success(entry)


@bp.get("/ledger-entries")
def list_ledger_entries():
    user_id, role = get_identity()
    require_roles(role, [ROLE_REVIEWER, ROLE_FINANCE, ROLE_SELLER])
    limit, offset = parse_pagination()
    items = list(db.ledger_entries.values())
    if role == ROLE_SELLER:
        items = [e for e in items if e["seller_id"] == user_id]
    for key in ("source_id", "seller_id", "source_type", "hold_state"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, pagination=meta)
