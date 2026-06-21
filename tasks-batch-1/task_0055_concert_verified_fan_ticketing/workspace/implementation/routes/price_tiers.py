"""PriceTier routes (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, require_int, sorted_by_creation

bp = Blueprint("price_tiers", __name__)


@bp.post("/price-tiers")
def create_price_tier():
    require_auth(["PromoterAdmin"])()
    body = get_json_body()
    event_id = require_str(body, "event_id")
    name = require_str(body, "name")
    allocation = require_int(body, "allocation")
    base_multiplier_bps = require_int(body, "base_multiplier_bps")

    event = get_or_404(db.events, event_id, "Event")

    if allocation <= 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "allocation must be > 0")
    if base_multiplier_bps < 10000:
        raise APIError(ERR_INVALID_REQUEST, 400, "base_multiplier_bps must be >= 10000")

    # Tiers may only be created while the event is DRAFT.
    if event["sales_status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "PriceTier only creatable while Event is DRAFT")

    tier = db.stamp_common(
        {
            "event_id": event_id,
            "name": name,
            "allocation": allocation,
            "base_multiplier_bps": base_multiplier_bps,
            "reserved_count": 0,
            "sold_count": 0,
        }
    )
    db.price_tiers[tier["id"]] = tier
    return ok_object(tier, 201)


@bp.get("/price-tiers/<tid>")
def get_price_tier(tid):
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    tier = get_or_404(db.price_tiers, tid, "PriceTier")
    return ok_object(tier, 200)


@bp.get("/price-tiers")
def list_price_tiers():
    require_auth(["Anonymous", "Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    event_id = request.args.get("event_id")
    items = list(db.price_tiers.values())
    if event_id is not None:
        items = [t for t in items if t.get("event_id") == event_id]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
