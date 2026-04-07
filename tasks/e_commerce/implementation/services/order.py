"""Order lifecycle service: create, pay, confirm, cancel, fulfill, deliver."""

import threading
from datetime import datetime, timedelta, timezone

import db

# Simple lock for payment state transitions to prevent double-pay race
_pay_lock = threading.Lock()
from config import (
    MIN_ORDER_TOTAL,
    RESERVATION_TIMEOUT_MINUTES,
    VALID_PAYMENT_METHODS,
)
from errors import (
    ERR_CROSS_SHOP_ORDER,
    ERR_FULFILLMENT_NOT_PROCESSING,
    ERR_FULFILLMENT_NOT_SHIPPED,
    ERR_INSUFFICIENT_INVENTORY,
    ERR_INVALID_REQUEST,
    ERR_ORDER_NOT_CONFIRMED,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_NOT_PAID,
    ERR_ORDER_NOT_PAYING,
    ERR_ORDER_NOT_UNPAID,
    ERR_PRODUCT_NOT_LISTED,
    ERR_RESERVATION_EXPIRED,
    ERR_SHOP_NOT_ACTIVE,
    raise_error,
)
from money import round_money
from services.commission import calculate_commission
from services.discount import calculate_discount
from services.shop import get_shop
from services.product import get_product


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_order_status(payment_status, fulfillment_status):
    """Derive the high-level order status from payment + fulfillment."""
    if payment_status in ("UNPAID", "PAYING"):
        return "CREATED"
    if fulfillment_status == "DELIVERED":
        return "COMPLETED"
    if payment_status in ("PAID", "PARTIAL_REFUND"):
        return "CONFIRMED"
    return "CREATED"


def _now_str():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _get_order(order_id):
    order = db.find_one("orders", id=order_id)
    if not order:
        raise_error(ERR_ORDER_NOT_FOUND, f"Order {order_id} not found.")
    return order


def _reservation_expired(order):
    expires = order.get("reservation_expires_at", "")
    if not expires:
        return True
    return _now_str() > expires


# ---------------------------------------------------------------------------
# create_order
# ---------------------------------------------------------------------------

def create_order(data, customer_id):
    """Create a new order with inventory reservation.

    ``data`` must contain shop_id, items (list of {product_id, quantity}),
    and optionally payment_method.
    """
    shop_id = data.get("shop_id")
    items = data.get("items") or []
    if not shop_id or not items:
        raise_error(ERR_INVALID_REQUEST, "shop_id and items are required.")

    shop = get_shop(shop_id)
    if shop.get("status") != "ACTIVE":
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop is not active.")

    # Validate payment method if provided
    payment_method = data.get("payment_method")
    if payment_method and payment_method not in VALID_PAYMENT_METHODS:
        raise_error(ERR_INVALID_REQUEST, f"Invalid payment method: {payment_method}")

    # Validate products — all must be LISTED and belong to same shop
    products = []
    for item in items:
        # First check if product exists at all (in any shop)
        product = db.find_one("products", id=item["product_id"])
        if not product:
            from errors import ERR_PRODUCT_NOT_FOUND
            raise_error(ERR_PRODUCT_NOT_FOUND, f"Product {item['product_id']} not found.")
        if product["shop_id"] != shop_id:
            raise_error(ERR_CROSS_SHOP_ORDER, "All products must be from the same shop.")
        if product.get("status") != "LISTED":
            raise_error(ERR_PRODUCT_NOT_LISTED, f"Product {product['id']} is not listed.")
        products.append((item, product))

    # --- Atomic inventory reservation ---
    reserved = []
    try:
        for item, product in products:
            qty = item["quantity"]
            new_reserved = product.get("reserved_count", 0) + qty
            inv = product.get("inventory_count", 0)
            available = inv - new_reserved
            if available < 0:
                raise_error(
                    ERR_INSUFFICIENT_INVENTORY,
                    f"Insufficient inventory for product {product['id']}.",
                )
            db.update("products", product["id"], {
                "reserved_count": new_reserved,
                "available_count": available,
            })
            reserved.append((product, qty))
    except Exception:
        # Rollback all reservations made so far
        for prod, qty in reserved:
            current = db.find_one("products", id=prod["id"])
            new_reserved = max((current or prod).get("reserved_count", 0) - qty, 0)
            inv = (current or prod).get("inventory_count", 0)
            db.update("products", prod["id"], {
                "reserved_count": new_reserved,
                "available_count": inv - new_reserved,
            })
        raise

    # --- Create order items with product snapshots ---
    subtotal = 0.0
    order_item_records = []
    items_with_products = []
    for item, product in products:
        qty = item["quantity"]
        unit_price = product["base_price"]
        line_total = round_money(unit_price * qty)
        subtotal = round_money(subtotal + line_total)
        items_with_products.append({
            "product": product,
            "quantity": qty,
            "unit_price": unit_price,
        })
        order_item_records.append({
            "product_id": product["id"],
            "product_snapshot": {
                "product_name": product.get("product_name", ""),
                "base_price": unit_price,
                "category": product.get("category", ""),
            },
            "unit_price": unit_price,
            "quantity": qty,
            "line_total": line_total,
        })

    # --- Discount ---
    discount_amount, applied_promotions = calculate_discount(
        shop, items_with_products, subtotal,
    )

    # Allocate discount proportionally across items
    if discount_amount > 0 and subtotal > 0:
        allocated = 0.0
        for idx, oi in enumerate(order_item_records):
            line = oi["line_total"]
            if idx < len(order_item_records) - 1:
                share = round_money(discount_amount * line / subtotal)
            else:
                # Last item gets the remainder to avoid rounding drift
                share = round_money(discount_amount - allocated)
            oi["discount_share"] = share
            allocated = round_money(allocated + share)
    else:
        for oi in order_item_records:
            oi["discount_share"] = 0.0

    # Compute final_price for each item
    for oi in order_item_records:
        oi["final_price"] = round_money(oi["line_total"] - oi["discount_share"])

    total_amount = round_money(max(subtotal - discount_amount, MIN_ORDER_TOTAL))

    # Reservation expiry
    expires_dt = datetime.now(timezone.utc) + timedelta(minutes=RESERVATION_TIMEOUT_MINUTES)
    reservation_expires_at = (
        expires_dt.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{expires_dt.microsecond // 1000:03d}Z"
    )

    # Increment promotion usage at order time
    for ap in applied_promotions:
        promo = db.find_one("promotions", id=ap["promotion_id"])
        if promo:
            db.update("promotions", promo["id"], {
                "usage_count": promo.get("usage_count", 0) + 1,
            })

    # --- Persist order ---
    order = db.insert("orders", {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "subtotal": subtotal,
        "discount_amount": discount_amount,
        "total_amount": total_amount,
        "payment_method": payment_method,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "order_status": "CREATED",
        "reservation_expires_at": reservation_expires_at,
        "applied_promotions": applied_promotions,
    })

    # Persist order items
    saved_items = []
    for oi in order_item_records:
        oi["order_id"] = order["id"]
        oi["shop_id"] = shop_id
        saved = db.insert("order_items", oi)
        saved_items.append(saved)

    order["items"] = saved_items
    return order


# ---------------------------------------------------------------------------
# pay_order
# ---------------------------------------------------------------------------

def pay_order(order_id, data, customer_id):
    """Initiate payment for an order."""
    with _pay_lock:
        order = _get_order(order_id)

        if order["payment_status"] != "UNPAID":
            raise_error(ERR_ORDER_NOT_UNPAID, "Order is not in UNPAID state.")

        if _reservation_expired(order):
            raise_error(ERR_RESERVATION_EXPIRED, "Reservation has expired.")

        payment_method = data.get("payment_method") or order.get("payment_method")
        if payment_method and payment_method not in VALID_PAYMENT_METHODS:
            raise_error(ERR_INVALID_REQUEST, f"Invalid payment method: {payment_method}")

        # Create payment record
        db.insert("payments", {
            "order_id": order_id,
            "type": "CHARGE",
            "status": "PENDING",
            "amount": order["total_amount"],
            "payment_method": payment_method,
        })

        db.update("orders", order_id, {
            "payment_status": "PAYING",
            "payment_method": payment_method,
            "order_status": _derive_order_status("PAYING", order["fulfillment_status"]),
        })

    return db.find_one("orders", id=order_id)


# ---------------------------------------------------------------------------
# confirm_payment
# ---------------------------------------------------------------------------

def confirm_payment(order_id):
    """Mark payment as successful."""
    order = _get_order(order_id)

    if order["payment_status"] != "PAYING":
        raise_error(ERR_ORDER_NOT_PAYING, "Order is not in PAYING state.")

    # Update payment record
    payment = db.find_one("payments", order_id=order_id, type="CHARGE", status="PENDING")
    if payment:
        db.update("payments", payment["id"], {"status": "SUCCESS"})

    # Convert reservation to committed: decrement reserved_count
    order_items = db.find_many("order_items", order_id=order_id)
    for oi in order_items:
        product = db.find_one("products", id=oi["product_id"])
        if product:
            new_reserved = max(product.get("reserved_count", 0) - oi["quantity"], 0)
            new_inventory = product.get("inventory_count", 0) - oi["quantity"]
            db.update("products", product["id"], {
                "reserved_count": new_reserved,
                "inventory_count": new_inventory,
                "available_count": new_inventory - new_reserved,
            })

    new_payment_status = "PAID"
    new_order_status = _derive_order_status(new_payment_status, order["fulfillment_status"])
    db.update("orders", order_id, {
        "payment_status": new_payment_status,
        "order_status": new_order_status,
    })

    return db.find_one("orders", id=order_id)


# ---------------------------------------------------------------------------
# payment_failed
# ---------------------------------------------------------------------------

def payment_failed(order_id):
    """Mark payment attempt as failed — retry allowed if not expired."""
    order = _get_order(order_id)

    if order["payment_status"] != "PAYING":
        raise_error(ERR_ORDER_NOT_PAYING, "Order is not in PAYING state.")

    payment = db.find_one("payments", order_id=order_id, type="CHARGE", status="PENDING")
    if payment:
        db.update("payments", payment["id"], {"status": "FAILED"})

    db.update("orders", order_id, {
        "payment_status": "UNPAID",
        "order_status": _derive_order_status("UNPAID", order["fulfillment_status"]),
    })

    return db.find_one("orders", id=order_id)


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

def cancel_order(order_id, customer_id):
    """Cancel an unpaid order and release reservations."""
    order = _get_order(order_id)

    if order["payment_status"] != "UNPAID":
        raise_error(ERR_ORDER_NOT_UNPAID, "Order is not in UNPAID state.")

    # Release reservations
    order_items = db.find_many("order_items", order_id=order_id)
    for oi in order_items:
        product = db.find_one("products", id=oi["product_id"])
        if product:
            new_reserved = max(product.get("reserved_count", 0) - oi["quantity"], 0)
            inv = product.get("inventory_count", 0)
            db.update("products", product["id"], {
                "reserved_count": new_reserved,
                "available_count": inv - new_reserved,
            })

    db.update("orders", order_id, {
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "order_status": "CANCELLED",
    })

    return db.find_one("orders", id=order_id)


# ---------------------------------------------------------------------------
# Fulfillment transitions
# ---------------------------------------------------------------------------

def start_processing(order_id):
    """Move order to PROCESSING fulfillment."""
    order = _get_order(order_id)

    if order["payment_status"] not in ("PAID", "PARTIAL_REFUND"):
        raise_error(ERR_ORDER_NOT_PAID, "Order must be paid before processing.")
    if order["order_status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "Order is not confirmed.")

    db.update("orders", order_id, {
        "fulfillment_status": "PROCESSING",
    })
    return db.find_one("orders", id=order_id)


def ship_order(order_id):
    """Mark order as shipped."""
    order = _get_order(order_id)

    if order["fulfillment_status"] != "PROCESSING":
        raise_error(ERR_FULFILLMENT_NOT_PROCESSING, "Order is not in PROCESSING state.")

    db.update("orders", order_id, {
        "fulfillment_status": "SHIPPED",
    })
    return db.find_one("orders", id=order_id)


def deliver_order(order_id):
    """Mark order as delivered — triggers commission and settlement balance."""
    order = _get_order(order_id)

    if order["fulfillment_status"] != "SHIPPED":
        raise_error(ERR_FULFILLMENT_NOT_SHIPPED, "Order is not in SHIPPED state.")

    shop = get_shop(order["shop_id"])
    shop_gmv = shop.get("monthly_gmv", 0.0)
    total = order["total_amount"]

    commission_amount, commission_rate = calculate_commission(shop_gmv, total)

    # Update shop financials
    new_gmv = round_money(shop_gmv + total)
    new_balance = round_money(shop.get("settlement_balance", 0.0) + total - commission_amount)
    db.update("shops", shop["id"], {
        "monthly_gmv": new_gmv,
        "settlement_balance": new_balance,
    })

    db.update("orders", order_id, {
        "fulfillment_status": "DELIVERED",
        "order_status": "COMPLETED",
        "commission_amount": commission_amount,
        "commission_rate": commission_rate,
    })

    return db.find_one("orders", id=order_id)


# ---------------------------------------------------------------------------
# Read helpers used by routes
# ---------------------------------------------------------------------------

def get_order(order_id):
    """Fetch a single order with items included."""
    order = _get_order(order_id)
    order["items"] = db.find_many("order_items", order_id=order_id)
    return order


def list_orders(filters, limit, offset):
    """Paginated order listing."""
    return db.find("orders", filters=filters, limit=limit, offset=offset)
