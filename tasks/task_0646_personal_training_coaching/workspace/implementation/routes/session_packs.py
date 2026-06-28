"""SessionPack endpoints + invoice quote (PRD §3.3)."""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from helpers import (get_json_body, require_fields, require_positive_int,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import session_pack_view
from services import domain
from services import calculations as calc

bp = Blueprint("session_packs", __name__)


@bp.route("/engagements/<engagement_id>/session-packs", methods=["POST"])
@require_roles("Trainer")
def create_session_pack(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)

    body = get_json_body()
    require_fields(body, "total_sessions", "price_cents")
    total_sessions = require_positive_int(body["total_sessions"], "total_sessions")
    price_cents = require_positive_int(body["price_cents"], "price_cents")

    pid = new_id()
    ts = now_ts()
    pack = {
        "id": pid,
        "engagement_id": engagement_id,
        "total_sessions": total_sessions,
        "price_cents": price_cents,
        "per_session_value_cents": calc.per_session_value_cents(price_cents, total_sessions),
        "sessions_committed": 0,
        "sessions_remaining": total_sessions,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.session_packs[pid] = pack
    return success(session_pack_view(pack), 201)


@bp.route("/engagements/<engagement_id>/session-packs", methods=["GET"])
@require_roles("Trainer", "Client")
def list_session_packs(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    limit, offset = pagination_params()
    items = [p for p in db.session_packs.values() if p["engagement_id"] == engagement_id]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([session_pack_view(p) for p in page], limit, offset, total, 200)


@bp.route("/session-packs/<pack_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_session_pack(pack_id):
    pack = domain.get_pack(pack_id)
    engagement = domain.get_engagement(pack["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(session_pack_view(pack), 200)


@bp.route("/engagements/<engagement_id>/session-packs/invoice", methods=["POST"])
@require_roles("Trainer")
def invoice_session_pack(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)

    body = get_json_body()
    require_fields(body, "line_items")
    line_items = body["line_items"]
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise errors.invalid_request("line_items must be a non-empty array")

    parsed = []
    for li in line_items:
        if not isinstance(li, dict):
            raise errors.invalid_request("each line item must be an object")
        if "list_price_cents" not in li or "discount_pct" not in li:
            raise errors.invalid_request("each line item needs list_price_cents and discount_pct")
        lp = li["list_price_cents"]
        dp = li["discount_pct"]
        if isinstance(lp, bool) or not isinstance(lp, int) or lp < 0:
            raise errors.invalid_request("list_price_cents must be a non-negative integer")
        if isinstance(dp, bool) or not isinstance(dp, (int, float)) or dp < 0 or dp > 1:
            raise errors.invalid_request("discount_pct must be a number in [0, 1]")
        parsed.append({"list_price_cents": lp, "discount_pct": dp})

    result = calc.invoice_breakdown(parsed)
    return success(result, 200)
