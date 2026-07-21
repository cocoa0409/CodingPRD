"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "account_type": "RETAIL",
        "name": "Test Customer",
        "region_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    """A pasteurized BY_WEIGHT cheese at 3000 cents/kg, min_aging 0, no shrink."""
    defaults = {
        "name": "Test Cheese",
        "category": "CHEESE",
        "milk_type": "COW",
        "pasteurized": True,
        "form": "WHEEL",
        "pricing_mode": "BY_WEIGHT",
        "price_per_kg_cents": 3000,
        "allergens": ["MILK"],
        "min_aging_days": 0,
        "target_aging_days": 0,
        "shrink_pct_per_day": 0,
    }
    defaults.update(overrides)
    return defaults


def create_by_unit_product_payload(**overrides) -> dict:
    """A BY_UNIT charcuterie at 700 cents/unit."""
    defaults = {
        "name": "Test Charcuterie",
        "category": "CHARCUTERIE",
        "milk_type": "NONE",
        "pasteurized": True,
        "form": "WHOLE_MUSCLE",
        "pricing_mode": "BY_UNIT",
        "unit_price_cents": 700,
        "allergens": ["PORK"],
        "min_aging_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_cave_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Cave",
        "temp_c": 12,
        "humidity_pct": 85,
        "capacity_g": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(product_id: str, cave_id: str, received_weight_g: int = 1000, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "cave_id": cave_id,
        "received_weight_g": received_weight_g,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, order_type: str = "RETAIL", **overrides) -> dict:
    defaults = {
        "order_type": order_type,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def create_product_line_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "line_type": "PRODUCT",
        "product_id": product_id,
    }
    defaults.update(overrides)
    return defaults


def create_board_line_payload(board_id: str, **overrides) -> dict:
    defaults = {
        "line_type": "BOARD",
        "board_id": board_id,
    }
    defaults.update(overrides)
    return defaults


def create_board_payload(components: list, **overrides) -> dict:
    defaults = {
        "name": "Test Board",
        "components": components,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, board_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "board_id": board_id,
        "tier": "CLASSIC",
        "monthly_price_cents": 5000,
        "cadence_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_prep_station_payload(**overrides) -> dict:
    defaults = {"name": "Test Station"}
    defaults.update(overrides)
    return defaults


def create_tasting_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Room",
        "seat_capacity": 20,
        "buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_tasting_event_payload(tasting_room_id: str, customer_id: str,
                                 start_at: str, end_at: str, seats: int = 5, **overrides) -> dict:
    defaults = {
        "tasting_room_id": tasting_room_id,
        "customer_id": customer_id,
        "start_at": start_at,
        "end_at": end_at,
        "seats": seats,
    }
    defaults.update(overrides)
    return defaults
