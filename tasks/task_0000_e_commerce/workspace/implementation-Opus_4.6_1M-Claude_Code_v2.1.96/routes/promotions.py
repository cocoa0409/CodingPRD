import uuid
import json
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination, check_version
from response import success_response

bp = Blueprint("promotions", __name__)


def _get_shop_or_404(db, shop_id):
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    return shop


@bp.route("/shops/<shop_id>/promotions", methods=["POST"])
def create_promotion(shop_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")

    data = request.get_json(force=True, silent=True) or {}
    promo_name = data.get("promo_name")
    if not promo_name:
        raise_error("ERR_INVALID_REQUEST", "promo_name is required.")
    promo_type = data.get("promo_type")
    if promo_type not in ("PERCENTAGE", "FIXED_AMOUNT", "BUY_X_GET_Y_FREE"):
        raise_error("ERR_INVALID_REQUEST", "Invalid promo_type.")
    promo_value = data.get("promo_value")
    if promo_value is None:
        raise_error("ERR_INVALID_REQUEST", "promo_value is required.")
    promo_threshold = data.get("promo_threshold", 0)
    max_discount_cap = data.get("max_discount_cap")
    stackable = data.get("stackable", False)
    priority = data.get("priority", 0)
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if not start_time or not end_time:
        raise_error("ERR_INVALID_REQUEST", "start_time and end_time are required.")
    max_usage = data.get("max_usage")
    applicable_categories = data.get("applicable_categories", [])

    promo_id = str(uuid.uuid4())
    ts = now_iso()
    db.execute(
        """INSERT INTO promotions (id, shop_id, promo_name, promo_type, promo_value, promo_threshold,
           max_discount_cap, stackable, priority, start_time, end_time, max_usage, usage_count,
           applicable_categories, status, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'DRAFT', ?, ?, 1)""",
        (promo_id, shop_id, promo_name, promo_type, promo_value, promo_threshold,
         max_discount_cap, 1 if stackable else 0, priority, start_time, end_time,
         max_usage, json.dumps(applicable_categories), ts, ts),
    )
    db.commit()
    promo = row_to_dict(db.execute("SELECT * FROM promotions WHERE id=?", (promo_id,)).fetchone())
    return success_response(promo, 201)


@bp.route("/shops/<shop_id>/promotions", methods=["GET"])
def list_promotions(shop_id):
    get_auth()
    db = get_db()
    _get_shop_or_404(db, shop_id)
    limit, offset = parse_pagination(request.args)
    total = db.execute("SELECT COUNT(*) as cnt FROM promotions WHERE shop_id=?", (shop_id,)).fetchone()["cnt"]
    rows = db.execute(
        "SELECT * FROM promotions WHERE shop_id=? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (shop_id, limit, offset),
    ).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/shops/<shop_id>/promotions/<promo_id>", methods=["GET"])
def get_promotion(shop_id, promo_id):
    get_auth()
    db = get_db()
    _get_shop_or_404(db, shop_id)
    promo = db.execute("SELECT * FROM promotions WHERE id=? AND shop_id=?", (promo_id, shop_id)).fetchone()
    if not promo:
        raise_error("ERR_PROMOTION_NOT_FOUND")
    return success_response(row_to_dict(promo))


@bp.route("/shops/<shop_id>/promotions/<promo_id>/activate", methods=["POST"])
def activate_promotion(shop_id, promo_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    if shop["status"] != "ACTIVE":
        raise_error("ERR_SHOP_NOT_ACTIVE")
    promo = db.execute("SELECT * FROM promotions WHERE id=? AND shop_id=?", (promo_id, shop_id)).fetchone()
    if not promo:
        raise_error("ERR_PROMOTION_NOT_FOUND")
    if promo["status"] not in ("DRAFT", "PAUSED"):
        raise_error("ERR_PROMOTION_NOT_DRAFT_OR_PAUSED")

    current_time = now_iso()
    if promo["end_time"] <= current_time:
        raise_error("ERR_PROMOTION_EXPIRED")

    # Check priority uniqueness among active promotions
    conflict = db.execute(
        "SELECT id FROM promotions WHERE shop_id=? AND status='ACTIVE' AND priority=? AND id!=?",
        (shop_id, promo["priority"], promo_id),
    ).fetchone()
    if conflict:
        raise_error("ERR_DUPLICATE_PROMOTION_PRIORITY")

    db.execute(
        "UPDATE promotions SET status='ACTIVE', updated_at=?, version=version+1 WHERE id=?",
        (current_time, promo_id),
    )
    db.commit()
    promo = row_to_dict(db.execute("SELECT * FROM promotions WHERE id=?", (promo_id,)).fetchone())
    return success_response(promo)


@bp.route("/shops/<shop_id>/promotions/<promo_id>/pause", methods=["POST"])
def pause_promotion(shop_id, promo_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    promo = db.execute("SELECT * FROM promotions WHERE id=? AND shop_id=?", (promo_id, shop_id)).fetchone()
    if not promo:
        raise_error("ERR_PROMOTION_NOT_FOUND")
    if promo["status"] != "ACTIVE":
        raise_error("ERR_PROMOTION_NOT_ACTIVE")

    ts = now_iso()
    db.execute("UPDATE promotions SET status='PAUSED', updated_at=?, version=version+1 WHERE id=?", (ts, promo_id))
    db.commit()
    promo = row_to_dict(db.execute("SELECT * FROM promotions WHERE id=?", (promo_id,)).fetchone())
    return success_response(promo)


@bp.route("/shops/<shop_id>/promotions/<promo_id>/cancel", methods=["POST"])
def cancel_promotion(shop_id, promo_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    promo = db.execute("SELECT * FROM promotions WHERE id=? AND shop_id=?", (promo_id, shop_id)).fetchone()
    if not promo:
        raise_error("ERR_PROMOTION_NOT_FOUND")
    if promo["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise_error("ERR_INVALID_REQUEST", "Promotion cannot be cancelled from its current state.")

    ts = now_iso()
    db.execute("UPDATE promotions SET status='CANCELLED', updated_at=?, version=version+1 WHERE id=?", (ts, promo_id))
    db.commit()
    promo = row_to_dict(db.execute("SELECT * FROM promotions WHERE id=?", (promo_id,)).fetchone())
    return success_response(promo)
