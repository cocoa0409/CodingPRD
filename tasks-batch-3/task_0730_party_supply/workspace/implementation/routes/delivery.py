from __future__ import annotations
from flask import Blueprint, request

from db import db, stamp_common, parse_iso
from errors import raise_error, ERR_INVALID_REQUEST, ERR_DELIVERY_SLOT_CONFLICT
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, fetch, clean

bp = Blueprint("delivery", __name__)


@bp.route("/delivery-slots", methods=["POST"])
@require_roles("StoreClerk")
def create_slot():
    body = get_body()
    window_start = require_field(body, "window_start")
    window_end = require_field(body, "window_end")
    van_id = require_field(body, "van_id")
    setup_included = bool(body.get("setup_included", False))

    try:
        ws = parse_iso(window_start)
        we = parse_iso(window_end)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "window_start/end must be ISO 8601")
        return  # unreachable

    if not (ws < we):
        raise_error(ERR_INVALID_REQUEST, "window_start must precede window_end")

    # Half-open overlap check per van_id (priority 12)
    for other in db.delivery_slots.values():
        if other["van_id"] != van_id:
            continue
        if other["status"] == "CANCELLED":
            continue
        ows = parse_iso(other["window_start"])
        owe = parse_iso(other["window_end"])
        # half-open overlap: [ws, we) intersects [ows, owe) iff ws < owe and ows < we
        if ws < owe and ows < we:
            raise_error(ERR_DELIVERY_SLOT_CONFLICT, "DeliverySlot overlaps existing slot on same van")

    slot = {
        "window_start": window_start,
        "window_end": window_end,
        "van_id": van_id,
        "setup_included": setup_included,
        "order_id": None,
        "status": "AVAILABLE",
    }
    stamp_common(slot)
    db.delivery_slots[slot["id"]] = slot
    return created(clean(slot))


@bp.route("/delivery-slots/<id>", methods=["GET"])
@require_roles("StoreClerk")
def get_slot(id):
    return ok(clean(fetch(db.delivery_slots, id)))


@bp.route("/delivery-slots", methods=["GET"])
@require_roles("StoreClerk")
def list_slots():
    limit, offset = parse_limit_offset()
    order_id = request.args.get("order_id")
    van_id = request.args.get("van_id")
    status = request.args.get("status")
    items = list(db.delivery_slots.values())
    if order_id is not None:
        items = [s for s in items if s.get("order_id") == order_id]
    if van_id is not None:
        items = [s for s in items if s["van_id"] == van_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)
