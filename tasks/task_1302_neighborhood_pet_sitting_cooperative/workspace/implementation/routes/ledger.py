"""CreditLedgerEntry listing (chronological replay order)."""

from flask import Blueprint, request

import db
from middleware import pagination_params, require_roles
from response import ok_list
from routes.members import get_member_or_404
from serializers import ledger_view

bp = Blueprint("ledger", __name__)


@bp.get("/coop/members/<member_id>/credit-ledger")
def list_ledger(member_id):
    require_roles("CoopAdmin", "Member")
    get_member_or_404(member_id)
    items = [e for e in db.store["ledger"].values() if e["member_id"] == member_id]
    entry_type = request.args.get("entry_type")
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    # Chronological replay: created_at ascending, id ascending as tiebreaker.
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ledger_view(e) for e in page], total, limit, offset)
