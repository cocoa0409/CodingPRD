"""/listings/{listing_id}/commission-splits — read-only listing."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from middleware import require_auth
from response import list_success
from routes._helpers import (
    enforce_listing_side_ownership,
    get_listing_or_404,
    parse_pagination,
    sort_by_created_at,
)
from services.serializers import commission_split as serialize_cs


bp = Blueprint("commission_splits", __name__)


@bp.get("/listings/<listing_id>/commission-splits")
@require_auth(["ListingAgent", "MlsAdmin"])
def list_commission_splits(listing_id):
    listing = get_listing_or_404(listing_id)
    if g.role == "ListingAgent":
        enforce_listing_side_ownership(listing)
    variant = request.args.get("variant")
    limit, offset = parse_pagination()
    rows = [cs for cs in store.commission_splits.values() if cs["listing_id"] == listing_id]
    if variant:
        rows = [r for r in rows if r["variant"] == variant]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([serialize_cs(r) for r in page], limit, offset, total, 200)
