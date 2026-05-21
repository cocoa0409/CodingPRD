"""Payload factories — one per entity, input fields only."""

import math
import uuid
from typing import Any, Dict, List, Optional


def _unique_suffix() -> str:
    """Short random suffix to keep fields like 'phone' unique across tests."""
    return uuid.uuid4().hex[:10]


# ──────────────────────────────────────────────────────────
# Geography helpers — produce lat/lng pairs that yield an exact haversine distance.
# ──────────────────────────────────────────────────────────

# A restaurant anchor: arbitrary but fixed, chosen well away from the poles.
REFERENCE_LAT = 37.0
REFERENCE_LNG = 0.0

# 1 deg of latitude along a meridian ≈ 111.1949 km. We offset the customer by
# exactly the number of degrees needed to land haversine at the target km.
_KM_PER_DEG_LAT = 111.1949


def coords_for_distance_km(target_km: float) -> Dict[str, float]:
    """Return lat/lng for a customer located *target_km* due-north of the reference
    restaurant. PRD §3.4 mandates haversine from the restaurant's coordinates to the
    customer's coordinates. Picking a pure-north offset keeps longitude constant and
    makes the resulting haversine exactly target_km to sub-millimetre precision."""
    d_lat = target_km / _KM_PER_DEG_LAT
    return {"lat": REFERENCE_LAT + d_lat, "lng": REFERENCE_LNG}


# ──────────────────────────────────────────────────────────
# Restaurant
# ──────────────────────────────────────────────────────────

def create_restaurant_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/restaurants (PRD §3.1).

    Required: name, address, lat, lng.
    Optional: commission_rate_override (in [0.05, 0.35] when set).
    """
    defaults: Dict[str, Any] = {
        "name": f"Test Restaurant {_unique_suffix()}",
        "address": "1 Reference Road",
        "lat": REFERENCE_LAT,
        "lng": REFERENCE_LNG,
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Rider
# ──────────────────────────────────────────────────────────

def create_rider_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/riders (PRD §3.3). Required: name, phone (unique)."""
    defaults: Dict[str, Any] = {
        "name": "Test Rider",
        "phone": f"+1555{_unique_suffix()[:7]}",
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Customer
# ──────────────────────────────────────────────────────────

def create_customer_payload(distance_km: float = 2.0, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/customers (PRD §3.2).

    Required: name, phone (unique), address, lat, lng.
    The default lat/lng place the customer exactly *distance_km* north of the
    reference restaurant; override `lat`/`lng` to customise placement.
    """
    coords = coords_for_distance_km(distance_km)
    defaults: Dict[str, Any] = {
        "name": "Test Customer",
        "phone": f"+1444{_unique_suffix()[:7]}",
        "address": "1 Customer Lane",
        "lat": coords["lat"],
        "lng": coords["lng"],
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Menu item
# ──────────────────────────────────────────────────────────

def create_menu_item_payload(**overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/restaurants/{id}/menu-items (PRD §3.1).

    Required: name, price_cents. Optional: is_listed (default true).
    """
    defaults: Dict[str, Any] = {
        "name": "Test Dish",
        "price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Order
# ──────────────────────────────────────────────────────────

def create_order_payload(
    customer_id: str,
    restaurant_id: str,
    items: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /api/orders (PRD §3.4).

    Required: customer_id, restaurant_id, items (non-empty array whose entries specify
    menu_item_id, name, unit_price_cents, quantity).
    """
    defaults: Dict[str, Any] = {
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "items": items if items is not None else [],
    }
    defaults.update(overrides)
    return defaults


def build_order_item(
    menu_item_id: str,
    name: str = "Test Dish",
    unit_price_cents: int = 1000,
    quantity: int = 1,
) -> Dict[str, Any]:
    """Construct a single entry of an Order.items array per PRD §3.4."""
    return {
        "menu_item_id": menu_item_id,
        "name": name,
        "unit_price_cents": unit_price_cents,
        "quantity": quantity,
    }


# ──────────────────────────────────────────────────────────
# Return
# ──────────────────────────────────────────────────────────

def create_return_payload(
    reason: str = "QUALITY_ISSUE",
    requested_refund_cents: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /api/orders/{id}/returns (PRD §3.9).

    Required: reason, requested_refund_cents.
    """
    defaults: Dict[str, Any] = {
        "reason": reason,
        "requested_refund_cents": requested_refund_cents,
    }
    defaults.update(overrides)
    return defaults


def approve_return_payload(approved_refund_cents: int, **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/returns/{id}/approve (PRD §3.9)."""
    defaults: Dict[str, Any] = {"approved_refund_cents": approved_refund_cents}
    defaults.update(overrides)
    return defaults


# ──────────────────────────────────────────────────────────
# Work order
# ──────────────────────────────────────────────────────────

def create_work_order_payload(
    opened_by_role: str,
    opened_by_id: str,
    category: str = "OTHER",
    related_order_id: Optional[str] = None,
    related_return_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Input fields for POST /api/work-orders (PRD §3.10).

    Required: opened_by_role, opened_by_id, category.
    Optional: related_order_id, related_return_id.
    """
    defaults: Dict[str, Any] = {
        "opened_by_role": opened_by_role,
        "opened_by_id": opened_by_id,
        "category": category,
    }
    if related_order_id is not None:
        defaults["related_order_id"] = related_order_id
    if related_return_id is not None:
        defaults["related_return_id"] = related_return_id
    defaults.update(overrides)
    return defaults


def resolve_work_order_payload(resolution_notes: str = "resolved", **overrides: Any) -> Dict[str, Any]:
    """Input fields for POST /api/work-orders/{id}/resolve (PRD §3.10)."""
    defaults: Dict[str, Any] = {"resolution_notes": resolution_notes}
    defaults.update(overrides)
    return defaults
