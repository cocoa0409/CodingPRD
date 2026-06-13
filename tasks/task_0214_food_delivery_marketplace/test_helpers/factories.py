"""Payload factories — one per entity, input fields only.

Defaults mirror the canonical "DT" zone and a route_distance_km=4 restaurant
used throughout the suite. Tests override only what they need to control.
"""
from .constants import ZONE_DT, ROUTE_DISTANCE_KM, PREP_MINUTES


def create_zone_payload(**overrides) -> dict:
    """Full zone config (all required + optional surge/service knobs)."""
    payload = dict(ZONE_DT)
    payload.update(overrides)
    return payload


def create_restaurant_payload(zone_id, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "name": "Burgers",
        "route_distance_km": ROUTE_DISTANCE_KM,
        "is_open": True,
        "prep_minutes": PREP_MINUTES,
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = {
        "name": "Combo",
        "price_cents": 2000,
        "available": True,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {"name": "Cara"}
    payload.update(overrides)
    return payload


def create_dasher_payload(home_zone_id, **overrides) -> dict:
    payload = {
        "name": "Dan",
        "home_zone_id": home_zone_id,
        "availability": "ONLINE",
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, restaurant_id, line_items, **overrides) -> dict:
    """line_items is a list of {menu_item_id, quantity} dicts."""
    payload = {
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def line_item(menu_item_id, quantity=1) -> dict:
    """Build a single line_items entry."""
    return {"menu_item_id": menu_item_id, "quantity": quantity}


def add_line_item_payload(menu_item_id, quantity=1, **overrides) -> dict:
    payload = {"menu_item_id": menu_item_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def tip_adjustment_payload(delta_cents, **overrides) -> dict:
    payload = {"delta_cents": delta_cents}
    payload.update(overrides)
    return payload


def issue_payload(line_item_id, missing_quantity, **overrides) -> dict:
    payload = {
        "line_item_id": line_item_id,
        "missing_quantity": missing_quantity,
    }
    payload.update(overrides)
    return payload


def dispatch_payload(expected_order_version) -> dict:
    return {"expected_order_version": expected_order_version}
