"""Product service: all product lifecycle business logic."""

import db
from errors import (
    raise_error,
    ERR_PRODUCT_NOT_FOUND,
    ERR_PRODUCT_NOT_DRAFT_OR_DELISTED,
    ERR_PRODUCT_NOT_LISTED_FOR_DELIST,
    ERR_PRODUCT_HAS_RESERVATIONS,
    ERR_SHOP_NOT_ACTIVE,
    ERR_INVALID_REQUEST,
)
from services.shop import get_shop


_PRODUCT_FIELDS = {"product_name", "category", "base_price", "inventory_count"}

def create_product(shop_id, data):
    """Create a new product in DRAFT status."""
    for field in ("product_name", "category", "base_price", "inventory_count"):
        if field not in data or data[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if data.get("inventory_count", 0) < 0:
        raise_error(ERR_INVALID_REQUEST, "inventory_count must be >= 0.")
    fields = {k: v for k, v in data.items() if k in _PRODUCT_FIELDS}
    inventory_count = fields.get("inventory_count", 0)
    record = db.insert("products", {
        **fields,
        "shop_id": shop_id,
        "status": "DRAFT",
        "reserved_count": 0,
        "available_count": inventory_count,
    })
    return record


def get_product(shop_id, product_id):
    """Retrieve a product by ID, ensuring it belongs to the given shop."""
    get_shop(shop_id)  # ensures shop exists
    product = db.find_one("products", id=product_id, shop_id=shop_id)
    if not product:
        raise_error(ERR_PRODUCT_NOT_FOUND, f"Product {product_id} not found in shop {shop_id}.")
    return product


def list_products(shop_id, filters, limit, offset):
    """Return paginated list of products for a shop."""
    get_shop(shop_id)
    query_filters = {**filters, "shop_id": shop_id}
    items, total = db.find("products", filters=query_filters, limit=limit, offset=offset)
    return items, total


def update_product(shop_id, product_id, data):
    """Update mutable product fields. Recalculate available_count if inventory_count changes."""
    product = get_product(shop_id, product_id)

    # OCC version check
    if "version" in data:
        if data["version"] != product["version"]:
            from errors import ERR_STALE_DATA
            raise_error(ERR_STALE_DATA, "Product has been modified by another request.")
        data = {k: v for k, v in data.items() if k != "version"}

    if not data:
        raise_error(ERR_INVALID_REQUEST, "No fields to update.")

    # Recalculate available_count when inventory_count is updated
    if "inventory_count" in data:
        new_inventory = data["inventory_count"]
        reserved = product["reserved_count"]
        data["available_count"] = new_inventory - reserved

    updated = db.update("products", product_id, data)
    return updated


def list_product(shop_id, product_id):
    """Transition product DRAFT|DELISTED -> LISTED. Shop must be ACTIVE."""
    shop = get_shop(shop_id)
    if shop["status"] != "ACTIVE":
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop must be ACTIVE to list products.")

    product = get_product(shop_id, product_id)
    if product["status"] not in ("DRAFT", "DELISTED"):
        raise_error(ERR_PRODUCT_NOT_DRAFT_OR_DELISTED, "Product must be DRAFT or DELISTED to list.")
    if product.get("base_price", 0) <= 0:
        raise_error(ERR_INVALID_REQUEST, "base_price must be > 0 to list.")
    if product.get("inventory_count", 0) < 0:
        raise_error(ERR_INVALID_REQUEST, "inventory_count must be >= 0 to list.")

    updated = db.update("products", product_id, {"status": "LISTED"})
    return updated


def delist_product(shop_id, product_id):
    """Transition product LISTED -> DELISTED."""
    product = get_product(shop_id, product_id)
    if product["status"] != "LISTED":
        raise_error(ERR_PRODUCT_NOT_LISTED_FOR_DELIST, "Product must be LISTED to delist.")

    updated = db.update("products", product_id, {"status": "DELISTED"})
    return updated


def archive_product(shop_id, product_id):
    """Transition product LISTED|DELISTED -> ARCHIVED. reserved_count must be 0."""
    product = get_product(shop_id, product_id)
    if product["status"] not in ("LISTED", "DELISTED"):
        raise_error(ERR_PRODUCT_NOT_DRAFT_OR_DELISTED, "Product must be LISTED or DELISTED to archive.")

    if product["reserved_count"] != 0:
        raise_error(ERR_PRODUCT_HAS_RESERVATIONS, "Product has outstanding reservations.")

    updated = db.update("products", product_id, {"status": "ARCHIVED"})
    return updated
