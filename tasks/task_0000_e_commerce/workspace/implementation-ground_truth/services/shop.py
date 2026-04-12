"""Shop service: all shop lifecycle business logic."""

import db
from errors import (
    raise_error,
    ERR_SHOP_NOT_FOUND,
    ERR_SHOP_NOT_PENDING_REVIEW,
    ERR_SHOP_NOT_ACTIVE,
    ERR_SHOP_HAS_PENDING_ORDERS,
    ERR_STALE_DATA,
    ERR_INVALID_REQUEST,
)


def _pick_shop_fields(data):
    """Extract only recognized shop fields, ignoring extra."""
    return {
        k: v for k, v in data.items()
        if k in ("shop_name", "owner_id", "description", "discount_strategy")
    }


def create_shop(data):
    """Create a new shop in PENDING_REVIEW status."""
    for field in ("shop_name", "owner_id"):
        if not data.get(field):
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    fields = _pick_shop_fields(data)
    fields.setdefault("discount_strategy", "PERCENTAGE_FIRST")
    record = db.insert("shops", {
        **fields,
        "status": "PENDING_REVIEW",
        "monthly_gmv": 0,
        "settlement_balance": 0,
    })
    return record


def get_shop(shop_id):
    """Retrieve a shop by ID or raise ERR_SHOP_NOT_FOUND."""
    shop = db.find_one("shops", id=shop_id)
    if not shop:
        raise_error(ERR_SHOP_NOT_FOUND, f"Shop {shop_id} not found.")
    return shop


def list_shops(filters, limit, offset):
    """Return paginated list of shops."""
    items, total = db.find("shops", filters=filters, limit=limit, offset=offset)
    return items, total


def update_shop(shop_id, data, user_id):
    """Update mutable shop fields with OCC version check."""
    shop = get_shop(shop_id)

    # OCC: if caller supplies a version, it must match
    if "version" in data:
        if data["version"] != shop["version"]:
            raise_error(ERR_STALE_DATA, "Shop has been modified by another request.")
        data = {k: v for k, v in data.items() if k != "version"}

    if not data:
        raise_error(ERR_INVALID_REQUEST, "No fields to update.")

    updated = db.update("shops", shop_id, data)
    return updated


def approve_shop(shop_id):
    """Transition shop PENDING_REVIEW -> ACTIVE."""
    shop = get_shop(shop_id)
    if shop["status"] != "PENDING_REVIEW":
        raise_error(ERR_SHOP_NOT_PENDING_REVIEW, "Shop is not in PENDING_REVIEW status.")
    updated = db.update("shops", shop_id, {
        "status": "ACTIVE",
        "monthly_gmv": 0,
        "settlement_balance": 0,
    })
    return updated


def suspend_shop(shop_id):
    """Transition shop ACTIVE -> SUSPENDED. Cascade: LISTED products -> DELISTED, ACTIVE promos -> PAUSED."""
    shop = get_shop(shop_id)
    if shop["status"] != "ACTIVE":
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop is not in ACTIVE status.")

    updated = db.update("shops", shop_id, {"status": "SUSPENDED"})

    # Cascade: delist all LISTED products
    listed_products = db.find_many("products", shop_id=shop_id, status="LISTED")
    for product in listed_products:
        db.update("products", product["id"], {"status": "DELISTED"})

    # Cascade: pause all ACTIVE promotions
    active_promos = db.find_many("promotions", shop_id=shop_id, status="ACTIVE")
    for promo in active_promos:
        db.update("promotions", promo["id"], {"status": "PAUSED"})

    return updated


def reinstate_shop(shop_id):
    """Transition shop SUSPENDED -> ACTIVE. Products/promos stay as-is."""
    shop = get_shop(shop_id)
    if shop["status"] != "SUSPENDED":
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop is not in SUSPENDED status.")
    updated = db.update("shops", shop_id, {"status": "ACTIVE"})
    return updated


def close_shop(shop_id):
    """Transition shop ACTIVE|SUSPENDED -> CLOSED.

    Preconditions:
      - No non-terminal orders (i.e. no orders in UNPAID, PAYING, PAID, CONFIRMED, PROCESSING, SHIPPED)
      - settlement_balance == 0
    Cascade:
      - Products -> ARCHIVED
      - Promotions -> CANCELLED
    """
    shop = get_shop(shop_id)
    if shop["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop must be ACTIVE or SUSPENDED to close.")

    # Check no non-terminal orders
    non_terminal_order_statuses = ("CREATED", "CONFIRMED")
    shop_orders = db.find_many("orders", shop_id=shop_id)
    pending = [o for o in shop_orders if o.get("order_status") in non_terminal_order_statuses]
    if pending:
        raise_error(ERR_SHOP_HAS_PENDING_ORDERS, "Shop has non-terminal orders.")

    # Check settlement balance is zero
    if shop.get("settlement_balance", 0) != 0:
        raise_error(ERR_SHOP_HAS_PENDING_ORDERS, "Shop has unsettled balance.")

    updated = db.update("shops", shop_id, {"status": "CLOSED"})

    # Cascade: archive all non-archived products
    products = db.find_many("products", shop_id=shop_id)
    for p in products:
        if p["status"] != "ARCHIVED":
            db.update("products", p["id"], {"status": "ARCHIVED"})

    # Cascade: cancel all non-cancelled promotions
    promos = db.find_many("promotions", shop_id=shop_id)
    for pr in promos:
        if pr["status"] != "CANCELLED":
            db.update("promotions", pr["id"], {"status": "CANCELLED"})

    return updated
