"""Payload factories — one per entity, input fields only."""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "alice@example.com",
        "full_name": "Alice",
        "delivery_zone": "ZONE_A",
        "address_line": "1 Fern Way",
    }
    defaults.update(overrides)
    return defaults


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": "TestPlant",
        "light_tag": "MEDIUM",
        "care_tag": "EASY",
        "weight_class": "LIGHT",
        "unit_price_cents": 3000,
        "warranty_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_stock_unit_payload(**overrides) -> dict:
    defaults = {"acquisition_date": "2026-03-25T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_delivery_driver_payload(**overrides) -> dict:
    defaults = {"name": "TestDriver"}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_zone": "ZONE_A",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(driver_id: str, window_start_at: str, window_end_at: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_tier": "STARTER",
        "care_tag_preference": "EASY",
        "light_tag_preference": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_workshop_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Workshop",
        "topic": "REPOTTING",
        "room_id": "STUDIO_A",
        "start_at": "2026-05-01T10:00:00Z",
        "end_at": "2026-05-01T12:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_workshop_registration_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(orderline_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "orderline_id": orderline_id,
        "customer_id": customer_id,
        "reason": "MORTALITY",
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_type": "PROCUREMENT",
        "sku_description": "Test special order",
    }
    defaults.update(overrides)
    return defaults


def create_care_log_payload(**overrides) -> dict:
    defaults = {"entry_type": "WATER", "note": ""}
    defaults.update(overrides)
    return defaults
