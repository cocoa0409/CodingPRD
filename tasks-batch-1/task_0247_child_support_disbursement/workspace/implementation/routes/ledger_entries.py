"""LedgerEntry read routes (audit trail, chronological)."""

from flask import Blueprint, request

import lookup
from common import pagination, paginate
from db import store
from middleware import require_roles
from response import object_response, array_response
from services import serialize

bp = Blueprint("ledger_entries", __name__)


def _chronological(items):
    """Chronological replay order keyed by effective_at, then created_at, id."""
    return sorted(items, key=lambda e: (e.get("effective_at", ""),
                                        e.get("created_at", ""), e.get("id", "")))


@bp.route("/ledger-entries", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def list_ledger_entries(auth):
    so_id = request.args.get("support_order_id")
    entry_type = request.args.get("entry_type")
    items = list(store.ledger_entries.values())
    if so_id is not None:
        items = [e for e in items if e["support_order_id"] == so_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    items = _chronological(items)
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return array_response([serialize.ledger_entry(e) for e in page],
                          limit, offset, total, 200)


@bp.route("/ledger-entries/<rid>", methods=["GET"])
@require_roles("CaseWorker", "FinanceOfficer")
def get_ledger_entry(auth, rid):
    rec = lookup.ledger_entry(rid)
    return object_response(serialize.ledger_entry(rec), 200)
