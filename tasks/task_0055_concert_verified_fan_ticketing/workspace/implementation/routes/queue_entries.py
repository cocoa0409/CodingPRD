"""QueueEntry routes (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_FAN_FLAGGED,
    ERR_FAN_NOT_VERIFIED,
    ERR_INVALID_PRESALE_CODE,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import get_or_404, require_str, require_int, sorted_by_creation
from services import calculations
from services.cascades import flag_fan_cascade

bp = Blueprint("queue_entries", __name__)


@bp.post("/queue-entries")
def join_queue():
    require_auth(["Fan"])()
    body = get_json_body()
    event_id = require_str(body, "event_id")
    fan_id = require_str(body, "fan_id")
    tier_id = require_str(body, "tier_id")
    presale_code_used = require_str(body, "presale_code_used", allow_empty=True)
    requested_qty = require_int(body, "requested_qty")

    # existence (left-to-right: event, tier, fan)
    event = get_or_404(db.events, event_id, "Event")
    tier = get_or_404(db.price_tiers, tier_id, "PriceTier")
    fan = get_or_404(db.fans, fan_id, "Fan")

    # ownership: acting Fan owns the resource being created (fan_id)
    if g.user_id != fan_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner")

    # (no state gate on the fan for join beyond verification dimension)

    # priority 6: flag bar
    if fan["verification_status"] == "FLAGGED":
        raise APIError(ERR_FAN_FLAGGED, 403, "Fan is flagged")

    # priority 7: presale-code gate (only during PRESALE)
    if event["sales_status"] == "PRESALE":
        if presale_code_used != event["presale_code"]:
            raise APIError(ERR_INVALID_PRESALE_CODE, 422, "Invalid presale code")

    # priority 9: verified-fan restriction
    if fan["verification_status"] != "VERIFIED":
        raise APIError(ERR_FAN_NOT_VERIFIED, 422, "Fan is not verified")

    # requested_qty range 1..MAX_PER_FAN
    if requested_qty < 1 or requested_qty > calculations.MAX_PER_FAN:
        raise APIError(ERR_INVALID_REQUEST, 400, "requested_qty must be in 1..6")

    # assign queue_position: 1-based rank by join time among this event's entries.
    existing = [qe for qe in db.queue_entries.values() if qe.get("event_id") == event_id]
    position = len(existing) + 1

    qe = db.stamp_common(
        {
            "event_id": event_id,
            "fan_id": fan_id,
            "tier_id": tier_id,
            "presale_code_used": presale_code_used,
            "queue_position": position,
            "requested_qty": requested_qty,
            "status": "WAITING",
            "offer_expires_at": None,
        }
    )
    db.queue_entries[qe["id"]] = qe

    # recompute risk_score (includes the just-created entry in the velocity window)
    fan["risk_score"] = calculations.bot_risk_score(fan)
    db.bump(fan)
    # a previously VERIFIED fan may flip to FLAGGED on the spot, cascading revokes
    if (
        fan["verification_status"] == "VERIFIED"
        and fan["risk_score"] >= calculations.BOT_FLAG_THRESHOLD
    ):
        flag_fan_cascade(fan)

    return ok_object(qe, 201)


@bp.get("/queue-entries/<qid>")
def get_queue_entry(qid):
    require_auth(["Fan", "PromoterAdmin"])()
    qe = get_or_404(db.queue_entries, qid, "QueueEntry")
    return ok_object(qe, 200)


@bp.get("/queue-entries")
def list_queue_entries():
    require_auth(["Fan", "PromoterAdmin"])()
    limit, offset = paginate_params(request.args)
    event_id = request.args.get("event_id")
    fan_id = request.args.get("fan_id")
    tier_id = request.args.get("tier_id")
    status = request.args.get("status")
    items = list(db.queue_entries.values())
    if event_id is not None:
        items = [q for q in items if q.get("event_id") == event_id]
    if fan_id is not None:
        items = [q for q in items if q.get("fan_id") == fan_id]
    if tier_id is not None:
        items = [q for q in items if q.get("tier_id") == tier_id]
    if status is not None:
        items = [q for q in items if q.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
