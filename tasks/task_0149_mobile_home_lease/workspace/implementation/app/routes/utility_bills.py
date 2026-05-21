"""Utility Bill routes (read-only listing)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..responses import list_response
from ..services.entities import get_lot_or_404
from ..services.serialization import serialize_utility_bill
from ..store import store
from ..validation import parse_pagination


bp = Blueprint("utility_bills", __name__)


@bp.route("/lots/<lot_id>/utility-bills", methods=["GET"])
@require_auth("ParkManager", "PlatformAdmin", "Resident")
def list_utility_bills(lot_id: str):
    get_lot_or_404(lot_id)
    limit, offset = parse_pagination()
    bills = [b for b in store.utility_bills.values() if b["lot_id"] == lot_id]
    bills.sort(key=lambda b: b["created_at"])
    total = len(bills)
    page = bills[offset: offset + limit]
    return list_response(
        [serialize_utility_bill(b) for b in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )


__all__ = ["bp"]
