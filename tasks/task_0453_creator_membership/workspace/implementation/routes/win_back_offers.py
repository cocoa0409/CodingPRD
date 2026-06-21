"""Win-back offer endpoints (PRD §3.6)."""
from flask import Blueprint, request

import errors
import response
from db import db, iso_millis
from middleware import require_auth, require_role
from services import serialize, calc
from services.common import (init_common, get_body, parse_pagination, paginate)
from services.lookups import get_pledge, get_offer

bp = Blueprint("win_back_offers", __name__)


def _parse_iso(s):
    from datetime import datetime, timezone
    if s is None:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@bp.post("/win-back-offers")
def create_offer():
    ctx = require_auth()
    require_role(ctx, {"Creator", "PlatformAdmin"})
    body = get_body()

    pledge_id = body.get("pledge_id")
    if pledge_id is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: pledge_id")
    pledge = get_pledge(pledge_id)

    discount_pct = body.get("discount_pct", 0.30)
    if discount_pct is None:
        discount_pct = 0.30
    if isinstance(discount_pct, bool) or not isinstance(discount_pct, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, "discount_pct must be a number")
    if not (0 < discount_pct < 1):
        errors.fail(errors.ERR_INVALID_REQUEST, "discount_pct must be in (0, 1)")

    # expires_at = lapsed_at + 60d (calc win_back_offer_expiry, PRD §3.6).
    lapsed_at = _parse_iso(pledge.get("lapsed_at"))
    expires_at = iso_millis(calc.win_back_offer_expiry(lapsed_at)) if lapsed_at else None

    rec = init_common({
        "pledge_id": pledge_id,
        "discount_pct": discount_pct,
        "expires_at": expires_at,
        "status": "OFFERED",
    })
    db.win_back_offers[rec["id"]] = rec
    return response.success(serialize.win_back_offer(rec), status=201)


@bp.get("/win-back-offers")
def list_offers():
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    limit, offset = parse_pagination()
    items = list(db.win_back_offers.values())
    for key in ("pledge_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    page, total = paginate(items, limit, offset)
    return response.list_success([serialize.win_back_offer(r) for r in page], limit, offset, total)


@bp.get("/win-back-offers/<offer_id>")
def get_one_offer(offer_id):
    ctx = require_auth()
    require_role(ctx, {"Creator", "Patron", "PlatformAdmin"})
    rec = get_offer(offer_id)
    return response.success(serialize.win_back_offer(rec))
