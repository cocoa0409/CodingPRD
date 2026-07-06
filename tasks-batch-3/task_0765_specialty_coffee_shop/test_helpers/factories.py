"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix="user"):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def create_bean_lot_payload(**overrides) -> dict:
    defaults = {
        "origin": "ETHIOPIA",
        "roast_level": "MEDIUM",
        "received_grams": 1000,
        "par_grams": 200,
        "price_per_gram_cents": 5,
    }
    defaults.update(overrides)
    return defaults


def create_modifier_payload(**overrides) -> dict:
    defaults = {
        "name": "Extra Shot",
        "modifier_group": "SHOT",
        "surcharge_cents": 90,
        "extra_bean_grams": 9,
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "name": "Latte LG",
        "category": "BEVERAGE",
        "base_price_cents": 450,
        "required_equipment_type": "ESPRESSO",
        "size": "LARGE",
        "bean_grams": 18,
        "origin_required": True,
        "bean_origin": "ETHIOPIA",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "name": "La Marzocco #1",
        "equipment_type": "ESPRESSO",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "equipment_id": None,
        "start_at": "2026-03-02T10:00:00Z",
        "end_at": "2026-03-02T11:00:00Z",
        "kind": "REPAIR",
    }
    defaults.update(overrides)
    return defaults


def create_barista_payload(**overrides) -> dict:
    defaults = {
        "name": "Barista One",
        "station_role": "CATERING",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email("member"),
        "full_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "bean_origin": "ETHIOPIA",
        "frequency": "MONTHLY",
        "bags_per_cycle": 2,
        "next_ship_at": "2026-04-01T00:00:00Z",
        "expected_member_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_catering_event_payload(**overrides) -> dict:
    defaults = {
        "client_name": "Acme Corp",
        "assigned_equipment_id": None,
        "assigned_barista_id": None,
        "scheduled_start": "2026-03-02T14:00:00Z",
        "scheduled_end": "2026-03-02T15:00:00Z",
        "headcount": 30,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "business_date": "2026-03-02",
        "bean_lot_id": None,
    }
    defaults.update(overrides)
    return defaults
