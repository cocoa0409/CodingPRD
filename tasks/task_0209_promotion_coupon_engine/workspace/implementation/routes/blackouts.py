"""BlackoutWindow endpoints (PRD §3.3). Immutable: id + created_at only."""
from flask import Blueprint, request

from db import db, parse_dt
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    paginate,
    require_field,
    require_json_object,
    serialize,
    sort_by_created,
)

bp = Blueprint("blackouts", __name__)


@bp.post("/promotions/<promotion_id>/blackouts")
@require_roles("MerchantAdmin")
def create_blackout(promotion_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        body = require_json_object(request.get_json(silent=True))
        starts_at = require_field(body, "starts_at")
        ends_at = require_field(body, "ends_at")
        sa = parse_dt(starts_at)
        ea = parse_dt(ends_at)
        if sa is None or ea is None:
            raise err("ERR_INVALID_REQUEST", "starts_at/ends_at must be ISO 8601")
        if not (ea > sa):
            raise err("ERR_INVALID_WINDOW", "ends_at must be after starts_at")
        reason = body.get("reason")
        rec = new_record(
            {
                "promotion_id": promotion_id,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "reason": reason,
            },
            common=False,
        )
        db.blackout_windows[rec["id"]] = rec
        return success(serialize(rec), 201)


@bp.get("/promotions/<promotion_id>/blackouts")
@require_roles("MerchantAdmin", "Shopper")
def list_blackouts(promotion_id):
    with db.lock:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise err("ERR_NOT_FOUND", "Promotion not found")
        limit, offset = paginate(request.args)
        items = [
            b
            for b in db.blackout_windows.values()
            if b["promotion_id"] == promotion_id
        ]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([serialize(b) for b in page], limit, offset, total)
