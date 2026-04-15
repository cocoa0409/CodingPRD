"""Payload factories from scaffold Table 1 input fields."""
import uuid
import math
from datetime import datetime, timedelta, timezone


def _unique_suffix():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Restaurant
# ---------------------------------------------------------------------------

def create_restaurant_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Restaurant {_unique_suffix()}",
        "cuisine_type": "Italian",
        "address": "123 Main St, Testville",
        "latitude": 40.7128,
        "longitude": -74.0060,
        "commission_rate": 0.15,
        "average_prep_time_minutes": 20,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------

def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Item {_unique_suffix()}",
        "base_price_cents": 1200,
        "category": "main",
        "prep_time_minutes": 15,
        "is_available": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Customer {_unique_suffix()}",
        "phone": f"+1555{uuid.uuid4().hex[:7]}",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Rider
# ---------------------------------------------------------------------------

def create_rider_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Rider {_unique_suffix()}",
        "phone": f"+1666{uuid.uuid4().hex[:7]}",
        "vehicle_type": "MOTORCYCLE",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

def create_order_payload(customer_id, restaurant_id, items, **overrides) -> dict:
    """Create an order payload.

    Args:
        customer_id: The customer placing the order.
        restaurant_id: The target restaurant.
        items: List of dicts with menu_item_id and quantity keys.
        **overrides: Additional/override fields (tip_cents, promotion_id, etc.).
    """
    defaults = {
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "delivery_address": "456 Delivery Ave, Testville",
        "delivery_latitude": 40.7200,
        "delivery_longitude": -74.0000,
        "items": items,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Delivery assignment
# ---------------------------------------------------------------------------

def create_delivery_payload(rider_id, **overrides) -> dict:
    defaults = {"rider_id": rider_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------

def create_promotion_payload(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    defaults = {
        "code": f"PROMO{_unique_suffix().upper()}",
        "discount_type": "PERCENTAGE",
        "discount_value": 10,
        "minimum_order_cents": 1000,
        "max_uses": 100,
        "valid_from": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "valid_until": (now + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

def create_rating_payload(rater_type, rater_id, ratee_id, score=5, **overrides) -> dict:
    defaults = {
        "rater_type": rater_type,
        "rater_id": rater_id,
        "ratee_id": ratee_id,
        "score": score,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Complaint
# ---------------------------------------------------------------------------

def create_complaint_payload(filed_by, filer_id, **overrides) -> dict:
    defaults = {
        "filed_by": filed_by,
        "filer_id": filer_id,
        "category": "WRONG_ITEMS",
        "description": "Test complaint description",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Surge Zone
# ---------------------------------------------------------------------------

def create_surge_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_name": f"Zone {_unique_suffix()}",
        "center_latitude": 40.7128,
        "center_longitude": -74.0060,
        "radius_km": 10.0,
        "surge_multiplier": 1.5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Settlement run
# ---------------------------------------------------------------------------

def create_settlement_run_payload(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    defaults = {
        "period_start": (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "period_end": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Complaint resolution
# ---------------------------------------------------------------------------

def create_resolve_complaint_payload(resolution_type, resolution_amount_cents=None, **overrides) -> dict:
    defaults = {"resolution_type": resolution_type}
    if resolution_amount_cents is not None:
        defaults["resolution_amount_cents"] = resolution_amount_cents
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Wallet top-up
# ---------------------------------------------------------------------------

def create_top_up_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
