"""Payload factories — one per entity, input fields only."""
from .constants import dt, DEFAULTS


def create_ingredient_payload(**overrides) -> dict:
    payload = {
        "name": "Lettuce",
        "unit": "GRAM",
        "unit_cost_cents": DEFAULTS["INGREDIENT_UNIT_COST"],
        "on_hand_qty": DEFAULTS["INGREDIENT_ON_HAND"],
    }
    payload.update(overrides)
    return payload


def create_menu_item_payload(**overrides) -> dict:
    payload = {
        "name": "Salad",
        "category": "SIDE",
        "sell_price_cents_per_portion": DEFAULTS["MENU_SELL_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_recipe_line_payload(menu_item_id, ingredient_id, **overrides) -> dict:
    payload = {
        "menu_item_id": menu_item_id,
        "ingredient_id": ingredient_id,
        "qty_per_portion": DEFAULTS["RECIPE_QTY_PER_PORTION"],
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    payload = {
        "name": "Hot Line",
        "concurrent_capacity": DEFAULTS["STATION_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_equipment_item_payload(**overrides) -> dict:
    payload = {
        "name": "Chafer",
        "asset_type": "CHAFER",
        "total_units": DEFAULTS["EQUIPMENT_TOTAL_UNITS"],
        "rental_price_cents": DEFAULTS["EQUIPMENT_RENTAL_PRICE"],
    }
    payload.update(overrides)
    return payload


def create_staff_member_payload(**overrides) -> dict:
    payload = {
        "name": "Sam Server",
        "staff_role": "SERVER",
        "hourly_rate_cents": DEFAULTS["STAFF_HOURLY_RATE"],
    }
    payload.update(overrides)
    return payload


def create_event_order_payload(**overrides) -> dict:
    payload = {
        "guest_count": 50,
        "event_start": dt(9),
        "event_end": dt(17),
        "venue_address": DEFAULTS["VENUE"],
        "service_charge_pct": 0.20,
        "gratuity_pct": 0.15,
    }
    payload.update(overrides)
    return payload


def create_order_line_payload(event_order_id, menu_item_id, **overrides) -> dict:
    payload = {
        "event_order_id": event_order_id,
        "menu_item_id": menu_item_id,
        "portions_per_guest": 1.0,
    }
    payload.update(overrides)
    return payload


def create_production_run_payload(event_order_id, station_id, menu_item_id, **overrides) -> dict:
    payload = {
        "event_order_id": event_order_id,
        "station_id": station_id,
        "menu_item_id": menu_item_id,
        "portions": 50,
        "scheduled_start": dt(6),
        "scheduled_end": dt(8),
    }
    payload.update(overrides)
    return payload


def create_rental_reservation_payload(event_order_id, equipment_item_id, **overrides) -> dict:
    payload = {
        "event_order_id": event_order_id,
        "equipment_item_id": equipment_item_id,
        "qty": 1,
        "out_time": dt(10),
        "return_time": dt(16),
    }
    payload.update(overrides)
    return payload


def create_staff_assignment_payload(event_order_id, staff_member_id, **overrides) -> dict:
    payload = {
        "event_order_id": event_order_id,
        "staff_member_id": staff_member_id,
        "staff_role": "SERVER",
        "shift_start": dt(10),
        "shift_end": dt(16),
    }
    payload.update(overrides)
    return payload
