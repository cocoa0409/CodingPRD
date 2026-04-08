import uuid
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination, check_version
from response import success_response

bp = Blueprint("products", __name__)


def _get_shop_or_404(db, shop_id):
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    return shop


def _get_product_or_404(db, shop_id, product_id):
    _get_shop_or_404(db, shop_id)
    product = db.execute("SELECT * FROM products WHERE id=? AND shop_id=?", (product_id, shop_id)).fetchone()
    if not product:
        raise_error("ERR_PRODUCT_NOT_FOUND")
    return product


@bp.route("/shops/<shop_id>/products", methods=["POST"])
def create_product(shop_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    if shop["status"] != "ACTIVE":
        raise_error("ERR_SHOP_NOT_ACTIVE")

    data = request.get_json(force=True, silent=True) or {}
    product_name = data.get("product_name")
    if not product_name:
        raise_error("ERR_INVALID_REQUEST", "product_name is required.")
    category = data.get("category", "")
    base_price = data.get("base_price")
    if base_price is None or float(base_price) <= 0:
        raise_error("ERR_INVALID_REQUEST", "base_price must be greater than zero.")
    inventory_count = data.get("inventory_count", 0)
    if not isinstance(inventory_count, int) or inventory_count < 0:
        raise_error("ERR_INVALID_REQUEST", "inventory_count must be a non-negative integer.")

    product_id = str(uuid.uuid4())
    ts = now_iso()
    db.execute(
        """INSERT INTO products (id, shop_id, product_name, category, base_price, inventory_count, reserved_count, available_count, status, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'DRAFT', ?, ?, 1)""",
        (product_id, shop_id, product_name, category, base_price, inventory_count, inventory_count, ts, ts),
    )
    db.commit()
    product = row_to_dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    return success_response(product, 201)


@bp.route("/shops/<shop_id>/products", methods=["GET"])
def list_products(shop_id):
    get_auth()
    db = get_db()
    _get_shop_or_404(db, shop_id)
    limit, offset = parse_pagination(request.args)
    total = db.execute("SELECT COUNT(*) as cnt FROM products WHERE shop_id=?", (shop_id,)).fetchone()["cnt"]
    rows = db.execute(
        "SELECT * FROM products WHERE shop_id=? ORDER BY created_at ASC LIMIT ? OFFSET ?",
        (shop_id, limit, offset),
    ).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/shops/<shop_id>/products/<product_id>", methods=["GET"])
def get_product(shop_id, product_id):
    get_auth()
    db = get_db()
    product = _get_product_or_404(db, shop_id, product_id)
    return success_response(row_to_dict(product))


@bp.route("/shops/<shop_id>/products/<product_id>", methods=["PUT"])
def update_product(shop_id, product_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    product = db.execute("SELECT * FROM products WHERE id=? AND shop_id=?", (product_id, shop_id)).fetchone()
    if not product:
        raise_error("ERR_PRODUCT_NOT_FOUND")

    data = request.get_json(force=True, silent=True) or {}
    check_version(dict(product), data.get("version"))

    product_name = data.get("product_name", product["product_name"])
    category = data.get("category", product["category"])
    base_price = data.get("base_price", product["base_price"])
    if float(base_price) <= 0:
        raise_error("ERR_INVALID_REQUEST", "base_price must be greater than zero.")

    inventory_count = data.get("inventory_count", product["inventory_count"])
    reserved_count = product["reserved_count"]
    available_count = inventory_count - reserved_count

    ts = now_iso()
    db.execute(
        """UPDATE products SET product_name=?, category=?, base_price=?, inventory_count=?,
           available_count=?, updated_at=?, version=version+1 WHERE id=?""",
        (product_name, category, base_price, inventory_count, available_count, ts, product_id),
    )
    db.commit()
    product = row_to_dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    return success_response(product)


@bp.route("/shops/<shop_id>/products/<product_id>/list", methods=["POST"])
def list_product(shop_id, product_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    if shop["status"] != "ACTIVE":
        raise_error("ERR_SHOP_NOT_ACTIVE")
    product = db.execute("SELECT * FROM products WHERE id=? AND shop_id=?", (product_id, shop_id)).fetchone()
    if not product:
        raise_error("ERR_PRODUCT_NOT_FOUND")
    if product["status"] not in ("DRAFT", "DELISTED"):
        raise_error("ERR_PRODUCT_NOT_DRAFT_OR_DELISTED")

    ts = now_iso()
    db.execute("UPDATE products SET status='LISTED', updated_at=?, version=version+1 WHERE id=?", (ts, product_id))
    db.commit()
    product = row_to_dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    return success_response(product)


@bp.route("/shops/<shop_id>/products/<product_id>/delist", methods=["POST"])
def delist_product(shop_id, product_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    product = db.execute("SELECT * FROM products WHERE id=? AND shop_id=?", (product_id, shop_id)).fetchone()
    if not product:
        raise_error("ERR_PRODUCT_NOT_FOUND")
    if product["status"] != "LISTED":
        raise_error("ERR_PRODUCT_NOT_LISTED_FOR_DELIST")

    ts = now_iso()
    db.execute("UPDATE products SET status='DELISTED', updated_at=?, version=version+1 WHERE id=?", (ts, product_id))
    db.commit()
    product = row_to_dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    return success_response(product)


@bp.route("/shops/<shop_id>/products/<product_id>/archive", methods=["POST"])
def archive_product(shop_id, product_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    shop = _get_shop_or_404(db, shop_id)
    if shop["owner_id"] != user_id:
        raise_error("ERR_NOT_SHOP_OWNER")
    product = db.execute("SELECT * FROM products WHERE id=? AND shop_id=?", (product_id, shop_id)).fetchone()
    if not product:
        raise_error("ERR_PRODUCT_NOT_FOUND")
    if product["status"] not in ("LISTED", "DELISTED"):
        raise_error("ERR_INVALID_REQUEST", "Product must be LISTED or DELISTED to archive.")
    if product["reserved_count"] > 0:
        raise_error("ERR_PRODUCT_HAS_RESERVATIONS")

    ts = now_iso()
    db.execute("UPDATE products SET status='ARCHIVED', updated_at=?, version=version+1 WHERE id=?", (ts, product_id))
    db.commit()
    product = row_to_dict(db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    return success_response(product)
