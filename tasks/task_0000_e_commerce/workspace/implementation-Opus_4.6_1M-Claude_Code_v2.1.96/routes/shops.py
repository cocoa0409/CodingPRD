import uuid
import json
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination, check_version
from response import success_response

bp = Blueprint("shops", __name__)


@bp.route("/shops", methods=["POST"])
def create_shop():
    user_id, _ = require_role("Seller")
    data = request.get_json(force=True, silent=True) or {}
    shop_name = data.get("shop_name")
    if not shop_name:
        raise_error("ERR_INVALID_REQUEST", "shop_name is required.")
    owner_id = data.get("owner_id")
    if not owner_id:
        raise_error("ERR_INVALID_REQUEST", "owner_id is required.")
    description = data.get("description", "")
    discount_strategy = data.get("discount_strategy", "PERCENTAGE_FIRST")
    if discount_strategy not in ("PERCENTAGE_FIRST", "FIXED_FIRST"):
        raise_error("ERR_INVALID_REQUEST", "Invalid discount_strategy.")

    shop_id = str(uuid.uuid4())
    ts = now_iso()
    db = get_db()
    db.execute(
        """INSERT INTO shops (id, shop_name, owner_id, description, discount_strategy, status, monthly_gmv, settlement_balance, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, 'PENDING_REVIEW', 0, 0, ?, ?, 1)""",
        (shop_id, shop_name, owner_id, description, discount_strategy, ts, ts),
    )
    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop, 201)


@bp.route("/shops", methods=["GET"])
def list_shops():
    get_auth()
    limit, offset = parse_pagination(request.args)
    db = get_db()
    total = db.execute("SELECT COUNT(*) as cnt FROM shops").fetchone()["cnt"]
    rows = db.execute("SELECT * FROM shops ORDER BY created_at ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/shops/<shop_id>", methods=["GET"])
def get_shop(shop_id):
    get_auth()
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    return success_response(row_to_dict(shop))


@bp.route("/shops/<shop_id>", methods=["PUT"])
def update_shop(shop_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")

    data = request.get_json(force=True, silent=True) or {}
    check_version(dict(shop), data.get("version"))

    shop_name = data.get("shop_name", shop["shop_name"])
    description = data.get("description", shop["description"])
    discount_strategy = data.get("discount_strategy", shop["discount_strategy"])
    if discount_strategy not in ("PERCENTAGE_FIRST", "FIXED_FIRST"):
        raise_error("ERR_INVALID_REQUEST", "Invalid discount_strategy.")

    ts = now_iso()
    db.execute(
        """UPDATE shops SET shop_name=?, description=?, discount_strategy=?, updated_at=?, version=version+1
           WHERE id=?""",
        (shop_name, description, discount_strategy, ts, shop_id),
    )
    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop)


@bp.route("/shops/<shop_id>/approve", methods=["POST"])
def approve_shop(shop_id):
    require_role("PlatformAdmin")
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["status"] != "PENDING_REVIEW":
        raise_error("ERR_SHOP_NOT_PENDING_REVIEW")

    ts = now_iso()
    db.execute(
        "UPDATE shops SET status='ACTIVE', monthly_gmv=0, settlement_balance=0, updated_at=?, version=version+1 WHERE id=?",
        (ts, shop_id),
    )
    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop)


@bp.route("/shops/<shop_id>/suspend", methods=["POST"])
def suspend_shop(shop_id):
    require_role("PlatformAdmin")
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["status"] != "ACTIVE":
        raise_error("ERR_SHOP_NOT_ACTIVE")

    ts = now_iso()
    db.execute("UPDATE shops SET status='SUSPENDED', updated_at=?, version=version+1 WHERE id=?", (ts, shop_id))

    # Cascade: LISTED products -> DELISTED
    products = db.execute("SELECT id FROM products WHERE shop_id=? AND status='LISTED'", (shop_id,)).fetchall()
    for p in products:
        db.execute("UPDATE products SET status='DELISTED', updated_at=?, version=version+1 WHERE id=?", (ts, p["id"]))

    # Cascade: ACTIVE promotions -> PAUSED
    promos = db.execute("SELECT id FROM promotions WHERE shop_id=? AND status='ACTIVE'", (shop_id,)).fetchall()
    for pr in promos:
        db.execute("UPDATE promotions SET status='PAUSED', updated_at=?, version=version+1 WHERE id=?", (ts, pr["id"]))

    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop)


@bp.route("/shops/<shop_id>/reinstate", methods=["POST"])
def reinstate_shop(shop_id):
    require_role("PlatformAdmin")
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["status"] != "SUSPENDED":
        raise_error("ERR_SHOP_NOT_ACTIVE", "Shop is not in SUSPENDED state.")

    ts = now_iso()
    db.execute("UPDATE shops SET status='ACTIVE', updated_at=?, version=version+1 WHERE id=?", (ts, shop_id))
    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop)


@bp.route("/shops/<shop_id>/close", methods=["POST"])
def close_shop(shop_id):
    require_role("PlatformAdmin")
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error("ERR_SHOP_NOT_ACTIVE", "Shop must be ACTIVE or SUSPENDED to close.")

    # Check no non-terminal orders
    pending_orders = db.execute(
        "SELECT COUNT(*) as cnt FROM orders WHERE shop_id=? AND order_status IN ('CREATED','CONFIRMED')",
        (shop_id,),
    ).fetchone()["cnt"]

    from money import round2
    balance = round2(shop["settlement_balance"])
    if pending_orders > 0 or balance != 0:
        raise_error("ERR_SHOP_HAS_PENDING_ORDERS")

    ts = now_iso()
    db.execute("UPDATE shops SET status='CLOSED', updated_at=?, version=version+1 WHERE id=?", (ts, shop_id))

    # Cascade: non-archived products -> ARCHIVED (only if reserved_count == 0)
    products = db.execute(
        "SELECT id, reserved_count FROM products WHERE shop_id=? AND status NOT IN ('ARCHIVED')", (shop_id,)
    ).fetchall()
    for p in products:
        db.execute("UPDATE products SET status='ARCHIVED', updated_at=?, version=version+1 WHERE id=?", (ts, p["id"]))

    # Cascade: non-terminal promotions -> CANCELLED
    promos = db.execute(
        "SELECT id FROM promotions WHERE shop_id=? AND status NOT IN ('CANCELLED', 'EXPIRED')", (shop_id,)
    ).fetchall()
    for pr in promos:
        db.execute("UPDATE promotions SET status='CANCELLED', updated_at=?, version=version+1 WHERE id=?", (ts, pr["id"]))

    db.commit()
    shop = row_to_dict(db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone())
    return success_response(shop)
