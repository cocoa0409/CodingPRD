"""Promotion service: all promotion lifecycle business logic."""

import db
from errors import (
    raise_error,
    ERR_PROMOTION_NOT_FOUND,
    ERR_PROMOTION_NOT_DRAFT_OR_PAUSED,
    ERR_PROMOTION_NOT_ACTIVE,
    ERR_PROMOTION_EXPIRED,
    ERR_SHOP_NOT_ACTIVE,
    ERR_DUPLICATE_PROMOTION_PRIORITY,
    ERR_INVALID_REQUEST,
)
from services.shop import get_shop
from datetime import datetime, timezone


_PROMO_FIELDS = {
    "promo_name", "promo_type", "promo_value", "promo_threshold",
    "max_discount_cap", "stackable", "priority", "applicable_categories",
    "start_time", "end_time", "max_usage",
}

def create_promotion(shop_id, data):
    """Create a new promotion in DRAFT status."""
    for field in ("promo_name", "promo_type", "promo_value", "priority", "start_time", "end_time"):
        if field not in data or data[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    fields = {k: v for k, v in data.items() if k in _PROMO_FIELDS}
    fields.setdefault("promo_threshold", 0)
    fields.setdefault("stackable", False)
    fields.setdefault("applicable_categories", [])
    record = db.insert("promotions", {
        **fields,
        "shop_id": shop_id,
        "status": "DRAFT",
        "usage_count": 0,
    })
    return record


def get_promotion(shop_id, promotion_id):
    """Retrieve a promotion by ID, ensuring it belongs to the given shop."""
    get_shop(shop_id)
    promo = db.find_one("promotions", id=promotion_id, shop_id=shop_id)
    if not promo:
        raise_error(ERR_PROMOTION_NOT_FOUND, f"Promotion {promotion_id} not found in shop {shop_id}.")
    return promo


def list_promotions(shop_id, filters, limit, offset):
    """Return paginated list of promotions for a shop."""
    get_shop(shop_id)
    query_filters = {**filters, "shop_id": shop_id}
    items, total = db.find("promotions", filters=query_filters, limit=limit, offset=offset)
    return items, total


def activate_promotion(shop_id, promotion_id):
    """Transition promotion DRAFT|PAUSED -> ACTIVE.

    Preconditions:
      - Shop must be ACTIVE
      - end_time must be in the future
      - Priority must be unique among shop's ACTIVE promotions
    """
    shop = get_shop(shop_id)
    if shop["status"] != "ACTIVE":
        raise_error(ERR_SHOP_NOT_ACTIVE, "Shop must be ACTIVE to activate promotions.")

    promo = get_promotion(shop_id, promotion_id)
    if promo["status"] not in ("DRAFT", "PAUSED"):
        raise_error(ERR_PROMOTION_NOT_DRAFT_OR_PAUSED, "Promotion must be DRAFT or PAUSED to activate.")

    # Check end_time is in the future
    end_time_str = promo.get("end_time")
    if end_time_str:
        # Parse ISO format
        try:
            end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            end_time = None
        if end_time and end_time <= datetime.now(timezone.utc):
            raise_error(ERR_PROMOTION_EXPIRED, "Promotion end_time is in the past.")

    # Check priority uniqueness among ACTIVE promotions for this shop
    priority = promo.get("priority")
    if priority is not None:
        active_promos = db.find_many("promotions", shop_id=shop_id, status="ACTIVE")
        for ap in active_promos:
            if ap["id"] != promotion_id and ap.get("priority") == priority:
                raise_error(
                    ERR_DUPLICATE_PROMOTION_PRIORITY,
                    f"An active promotion with priority {priority} already exists.",
                )

    updated = db.update("promotions", promotion_id, {"status": "ACTIVE"})
    return updated


def pause_promotion(shop_id, promotion_id):
    """Transition promotion ACTIVE -> PAUSED."""
    promo = get_promotion(shop_id, promotion_id)
    if promo["status"] != "ACTIVE":
        raise_error(ERR_PROMOTION_NOT_ACTIVE, "Promotion must be ACTIVE to pause.")

    updated = db.update("promotions", promotion_id, {"status": "PAUSED"})
    return updated


def cancel_promotion(shop_id, promotion_id):
    """Transition promotion DRAFT|ACTIVE|PAUSED -> CANCELLED."""
    promo = get_promotion(shop_id, promotion_id)
    if promo["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise_error(ERR_INVALID_REQUEST, "Promotion cannot be cancelled from its current status.")

    updated = db.update("promotions", promotion_id, {"status": "CANCELLED"})
    return updated
