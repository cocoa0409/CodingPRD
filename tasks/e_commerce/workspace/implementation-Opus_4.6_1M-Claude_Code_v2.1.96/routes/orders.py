import uuid
import json
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request
from db import get_db
from errors import raise_error
from middleware import require_role, get_auth
from config import now_iso, row_to_dict, parse_pagination, check_version
from response import success_response
from money import round2, compute_commission
from services.discount import apply_promotions, distribute_discount

bp = Blueprint("orders", __name__)


def _get_order_or_404(db, order_id):
    order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise_error("ERR_ORDER_NOT_FOUND")
    return order


def _check_reservation_expired(order):
    if order["reservation_expires_at"]:
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(order["reservation_expires_at"].replace("Z", "+00:00"))
        if now > exp:
            return True
    return False


def _cancel_expired_order(db, order, ts):
    """Auto-cancel an expired unpaid order."""
    db.execute(
        "UPDATE orders SET payment_status='UNPAID', order_status='CANCELLED', updated_at=?, version=version+1 WHERE id=?",
        (ts, order["id"]),
    )
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
    for item in items:
        db.execute(
            "UPDATE products SET reserved_count=reserved_count-?, available_count=available_count+?, updated_at=?, version=version+1 WHERE id=?",
            (item["quantity"], item["quantity"], ts, item["product_id"]),
        )
    db.commit()


@bp.route("/orders", methods=["POST"])
def create_order():
    user_id, _ = require_role("Customer")
    data = request.get_json(force=True, silent=True) or {}
    shop_id = data.get("shop_id")
    if not shop_id:
        raise_error("ERR_INVALID_REQUEST", "shop_id is required.")
    shipping_address = data.get("shipping_address", "")
    items_data = data.get("items", [])
    if not items_data:
        raise_error("ERR_INVALID_REQUEST", "items are required.")

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id=?", (shop_id,)).fetchone()
    if not shop:
        raise_error("ERR_SHOP_NOT_FOUND")
    if shop["status"] != "ACTIVE":
        raise_error("ERR_SHOP_NOT_ACTIVE")

    # Validate products
    products = []
    for item in items_data:
        pid = item.get("product_id")
        qty = item.get("quantity", 0)
        if qty < 1:
            raise_error("ERR_INVALID_REQUEST", "quantity must be at least 1.")
        product = db.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
        if not product:
            raise_error("ERR_PRODUCT_NOT_FOUND")
        if product["shop_id"] != shop_id:
            raise_error("ERR_CROSS_SHOP_ORDER")
        if product["status"] != "LISTED":
            raise_error("ERR_PRODUCT_NOT_LISTED")
        if product["available_count"] < qty:
            raise_error("ERR_INSUFFICIENT_INVENTORY")
        products.append((product, qty))

    # Atomic reservation
    ts = now_iso()
    for product, qty in products:
        db.execute(
            "UPDATE products SET reserved_count=reserved_count+?, available_count=available_count-?, updated_at=?, version=version+1 WHERE id=?",
            (qty, qty, ts, product["id"]),
        )

    # Build order items in memory first
    order_id = str(uuid.uuid4())
    order_items = []
    subtotal = 0.0

    for product, qty in products:
        item_id = str(uuid.uuid4())
        unit_price = product["base_price"]
        line_total = round2(unit_price * qty)
        snapshot = json.dumps({
            "product_name": product["product_name"],
            "base_price": product["base_price"],
            "category": product["category"],
        })
        order_items.append({
            "id": item_id,
            "order_id": order_id,
            "product_id": product["id"],
            "product_snapshot": json.loads(snapshot),
            "product_snapshot_json": snapshot,
            "quantity": qty,
            "unit_price": unit_price,
            "line_total": line_total,
            "discount_share": 0.0,
            "final_price": line_total,
            "category": product["category"],
        })
        subtotal += line_total

    subtotal = round2(subtotal)

    # Evaluate promotions
    current_time = now_iso()
    promos = db.execute(
        "SELECT * FROM promotions WHERE shop_id=? AND status='ACTIVE'", (shop_id,)
    ).fetchall()

    item_categories = set()
    for oi in order_items:
        cat = oi.get("category", "")
        if cat:
            item_categories.add(cat)

    eligible = []
    for p in promos:
        p = dict(p)
        # Check time window
        if p["start_time"] > current_time or p["end_time"] <= current_time:
            continue
        # Check applicable_categories
        cats = p["applicable_categories"]
        if isinstance(cats, str):
            cats = json.loads(cats)
        if cats and not item_categories.intersection(set(cats)):
            continue
        # Check usage
        if p["max_usage"] is not None and p["usage_count"] >= p["max_usage"]:
            continue
        # Check threshold
        if p["promo_type"] == "BUY_X_GET_Y_FREE":
            total_qty = sum(oi["quantity"] for oi in order_items)
            if total_qty < p["promo_threshold"]:
                continue
        else:
            if subtotal < p["promo_threshold"]:
                continue
        eligible.append(p)

    # Handle stacking: at most one non-stackable, all stackable
    stackable_promos = [p for p in eligible if p["stackable"]]
    non_stackable_promos = [p for p in eligible if not p["stackable"]]
    non_stackable_promos.sort(key=lambda x: x["priority"])

    selected = list(stackable_promos)
    if non_stackable_promos:
        selected.append(non_stackable_promos[0])

    # If no promos selected but we had eligible non-stackable with exhausted usage, check special case
    if not selected and len(eligible) == 0 and len(promos) > 0:
        # Check if there's a single candidate that failed usage check
        pass

    discount_amount, total_amount, applied_promotions = apply_promotions(
        subtotal, order_items, selected, shop["discount_strategy"]
    )

    # Distribute discount across items
    if discount_amount > 0:
        order_items = distribute_discount(order_items, discount_amount, subtotal)

    # Reservation expiry: current time + 30 minutes
    exp_dt = datetime.now(timezone.utc) + timedelta(minutes=30)
    reservation_expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{exp_dt.microsecond // 1000:03d}Z"

    # Insert order first (parent), then items (children)
    db.execute(
        """INSERT INTO orders (id, shop_id, customer_id, shipping_address, subtotal, discount_amount, total_amount,
           payment_status, fulfillment_status, order_status, reservation_expires_at, applied_promotions,
           commission_amount, commission_rate, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'UNPAID', 'PENDING', 'CREATED', ?, ?, 0, 0, ?, ?, 1)""",
        (order_id, shop_id, user_id, shipping_address, subtotal, discount_amount, total_amount,
         reservation_expires_at, json.dumps(applied_promotions), ts, ts),
    )

    # Now insert order items
    for oi in order_items:
        db.execute(
            """INSERT INTO order_items (id, order_id, product_id, product_snapshot, quantity, unit_price, line_total, discount_share, final_price, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (oi["id"], order_id, oi["product_id"], oi["product_snapshot_json"], oi["quantity"],
             oi["unit_price"], oi["line_total"], oi["discount_share"], oi["final_price"], ts),
        )

    db.commit()

    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    items_rows = db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY created_at ASC", (order_id,)).fetchall()
    order["items"] = [row_to_dict(r) for r in items_rows]
    return success_response(order, 201)


@bp.route("/orders", methods=["GET"])
def list_orders():
    get_auth()
    limit, offset = parse_pagination(request.args)
    db = get_db()
    total = db.execute("SELECT COUNT(*) as cnt FROM orders").fetchone()["cnt"]
    rows = db.execute("SELECT * FROM orders ORDER BY created_at ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    data = [row_to_dict(r) for r in rows]
    pagination = {"limit": limit, "offset": offset, "total_count": total, "has_more": offset + limit < total}
    return success_response(data, 200, pagination)


@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    get_auth()
    db = get_db()
    order = _get_order_or_404(db, order_id)
    result = row_to_dict(order)
    items_rows = db.execute("SELECT * FROM order_items WHERE order_id=? ORDER BY created_at ASC", (order_id,)).fetchall()
    result["items"] = [row_to_dict(r) for r in items_rows]
    # Include payments
    payments = db.execute("SELECT * FROM payments WHERE order_id=? ORDER BY created_at ASC", (order_id,)).fetchall()
    result["payments"] = [row_to_dict(r) for r in payments]
    return success_response(result)


@bp.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    user_id, _ = require_role("Customer")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["customer_id"] != user_id:
        raise_error("ERR_NOT_ORDER_OWNER")
    if order["payment_status"] != "UNPAID":
        raise_error("ERR_ORDER_NOT_UNPAID")

    ts = now_iso()
    db.execute(
        "UPDATE orders SET order_status='CANCELLED', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )
    # Release reservations
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    for item in items:
        db.execute(
            "UPDATE products SET reserved_count=reserved_count-?, available_count=available_count+?, updated_at=?, version=version+1 WHERE id=?",
            (item["quantity"], item["quantity"], ts, item["product_id"]),
        )
    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    user_id, _ = require_role("Customer")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["customer_id"] != user_id:
        raise_error("ERR_NOT_ORDER_OWNER")
    if order["payment_status"] != "UNPAID":
        raise_error("ERR_ORDER_NOT_UNPAID")

    # Check reservation expiry
    if _check_reservation_expired(order):
        ts = now_iso()
        _cancel_expired_order(db, order, ts)
        raise_error("ERR_RESERVATION_EXPIRED")

    data = request.get_json(force=True, silent=True) or {}
    payment_method = data.get("payment_method")
    if payment_method not in ("CREDIT_CARD", "DEBIT_CARD", "WALLET", "BANK_TRANSFER"):
        raise_error("ERR_INVALID_REQUEST", "Invalid payment_method.")
    transaction_ref = data.get("transaction_ref")
    if not transaction_ref:
        raise_error("ERR_INVALID_REQUEST", "transaction_ref is required.")

    ts = now_iso()
    payment_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO payments (id, order_id, payment_type, payment_method, transaction_ref, amount, status, created_at)
           VALUES (?, ?, 'CHARGE', ?, ?, ?, 'PENDING', ?)""",
        (payment_id, order_id, payment_method, transaction_ref, order["total_amount"], ts),
    )
    db.execute(
        "UPDATE orders SET payment_status='PAYING', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )
    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/confirm-payment", methods=["POST"])
def confirm_payment(order_id):
    require_role("PlatformAdmin")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["payment_status"] != "PAYING":
        raise_error("ERR_ORDER_NOT_PAYING")

    ts = now_iso()
    # Update payment record
    db.execute(
        "UPDATE payments SET status='SUCCESS' WHERE order_id=? AND payment_type='CHARGE' AND status='PENDING'",
        (order_id,),
    )
    db.execute(
        "UPDATE orders SET payment_status='PAID', order_status='CONFIRMED', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )

    # Convert reservations: decrement reserved_count
    items = db.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    for item in items:
        db.execute(
            "UPDATE products SET reserved_count=reserved_count-?, updated_at=?, version=version+1 WHERE id=?",
            (item["quantity"], ts, item["product_id"]),
        )

    # Increment promotion usage_count
    applied = order["applied_promotions"]
    if isinstance(applied, str):
        applied = json.loads(applied)
    for ap in applied:
        db.execute(
            "UPDATE promotions SET usage_count=usage_count+1, updated_at=?, version=version+1 WHERE id=?",
            (ts, ap["promotion_id"]),
        )

    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/payment-failed", methods=["POST"])
def payment_failed(order_id):
    require_role("PlatformAdmin")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["payment_status"] != "PAYING":
        raise_error("ERR_ORDER_NOT_PAYING")

    ts = now_iso()
    db.execute(
        "UPDATE payments SET status='FAILED' WHERE order_id=? AND payment_type='CHARGE' AND status='PENDING'",
        (order_id,),
    )
    db.execute(
        "UPDATE orders SET payment_status='UNPAID', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )
    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/start-processing", methods=["POST"])
def start_processing(order_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["payment_status"] not in ("PAID", "PARTIAL_REFUND"):
        raise_error("ERR_ORDER_NOT_PAID")
    if order["order_status"] != "CONFIRMED":
        raise_error("ERR_ORDER_NOT_CONFIRMED")

    ts = now_iso()
    db.execute(
        "UPDATE orders SET fulfillment_status='PROCESSING', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )
    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/ship", methods=["POST"])
def ship_order(order_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["fulfillment_status"] != "PROCESSING":
        raise_error("ERR_FULFILLMENT_NOT_PROCESSING")

    ts = now_iso()
    db.execute(
        "UPDATE orders SET fulfillment_status='SHIPPED', updated_at=?, version=version+1 WHERE id=?",
        (ts, order_id),
    )
    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)


@bp.route("/orders/<order_id>/deliver", methods=["POST"])
def deliver_order(order_id):
    user_id, _ = require_role("Seller")
    db = get_db()
    order = _get_order_or_404(db, order_id)
    if order["fulfillment_status"] != "SHIPPED":
        raise_error("ERR_FULFILLMENT_NOT_SHIPPED")

    ts = now_iso()

    # Commission calculation
    shop = db.execute("SELECT * FROM shops WHERE id=?", (order["shop_id"],)).fetchone()
    commission_amount, commission_rate = compute_commission(order["total_amount"], shop["monthly_gmv"])

    net_revenue = round2(order["total_amount"] - commission_amount)

    db.execute(
        """UPDATE orders SET fulfillment_status='DELIVERED', order_status='COMPLETED',
           commission_amount=?, commission_rate=?, updated_at=?, version=version+1 WHERE id=?""",
        (commission_amount, commission_rate, ts, order_id),
    )

    # Update shop GMV and settlement balance
    db.execute(
        """UPDATE shops SET monthly_gmv=monthly_gmv+?, settlement_balance=settlement_balance+?,
           updated_at=?, version=version+1 WHERE id=?""",
        (order["total_amount"], net_revenue, ts, order["shop_id"]),
    )

    db.commit()
    order = row_to_dict(db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())
    return success_response(order)
