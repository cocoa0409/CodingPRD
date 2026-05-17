"""/pbm/ledger-entries — read-only audit ledger."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_roles
from ..envelope import list_success
from ..store import STORE
from ..validation import paginate, parse_pagination

bp = Blueprint("ledger", __name__)


def serialize_entry(e: dict) -> dict:
    return {
        "id": e["id"],
        "claim_id": e["claim_id"],
        "rebate_agreement_id": e["rebate_agreement_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "posted_at": e["posted_at"],
        "created_at": e["created_at"],
    }


@bp.get("/pbm/ledger-entries")
@require_roles("PBMAdmin")
def list_ledger():
    limit, offset = parse_pagination()
    claim_id = request.args.get("claim_id")
    agreement_id = request.args.get("rebate_agreement_id")
    entry_type = request.args.get("entry_type")
    with STORE.lock:
        items = list(STORE.ledger_entries.values())
    if claim_id:
        items = [e for e in items if e["claim_id"] == claim_id]
    if agreement_id:
        items = [e for e in items if e["rebate_agreement_id"] == agreement_id]
    if entry_type:
        items = [e for e in items if e["entry_type"] == entry_type]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return list_success(
        [serialize_entry(e) for e in page],
        limit=limit, offset=offset, total_count=total,
    )
