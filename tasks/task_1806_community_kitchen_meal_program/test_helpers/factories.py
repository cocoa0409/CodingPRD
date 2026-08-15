"""Payload factories — one per entity, input fields only (PRD section 4)."""
from typing import Any, Dict, Optional

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def unique_email() -> str:
    return f"vol{_next()}@example.org"


def unique_name(prefix: str) -> str:
    return f"{prefix} {_next()}"


def create_site_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": unique_name("Site"),
        "dine_in_capacity": 50,
        "togo_capacity_per_window": 20,
        "delivery_radius_km": 8,
    }
    defaults.update(overrides)
    return defaults


def create_menu_day_payload(site_id: str, service_date: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "service_date": service_date,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(name: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": name or unique_name("Item"),
        "planned_servings": 10,
    }
    defaults.update(overrides)
    return defaults


def create_food_batch_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "source_type": "PURCHASE",
        "item_description": "Test stock",
        "quantity_servings": 10,
        "received_at": "2026-08-10T07:00:00Z",
        "use_by": "2026-08-20T00:00:00Z",
        "unit_cost_cents_per_serving": 50,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(food_batch_id: str, servings: int) -> Dict[str, Any]:
    return {"food_batch_id": food_batch_id, "servings": servings}


def create_volunteer_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": unique_name("Volunteer"),
        "email": unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_shift_payload(
    site_id: str, volunteer_id: str, menu_day_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "volunteer_id": volunteer_id,
        "menu_day_id": menu_day_id,
        "role_on_shift": "SERVER",
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": unique_name("Guest"),
        "household_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_meal_service_payload(menu_day_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "menu_day_id": menu_day_id,
        "service_model": "DINE_IN",
        "window_start": "2026-08-10T11:00:00Z",
        "window_end": "2026-08-10T13:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_meal_order_payload(
    meal_service_id: str, guest_id: str, menu_item_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "meal_service_id": meal_service_id,
        "guest_id": guest_id,
        "menu_item_id": menu_item_id,
        "quantity": 1,
        "substitution_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_asset_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "name": unique_name("Asset"),
        "equipment_class": "OVEN",
        "criticality": "SUPPORT",
    }
    defaults.update(overrides)
    return defaults


def create_waste_log_payload(
    menu_day_id: str, food_batch_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "menu_day_id": menu_day_id,
        "food_batch_id": food_batch_id,
        "servings_wasted": 1,
        "reason": "SPOILAGE",
        "disposition": "DISCARD",
    }
    defaults.update(overrides)
    return defaults
