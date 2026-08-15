"""Payload factories — one per entity, input fields only."""
import uuid

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def unique_vin() -> str:
    """17-character VIN-shaped unique identifier."""
    return ("1FUJ" + uuid.uuid4().hex.upper().replace("-", ""))[:17]


def unique_code(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_customer_account_payload(**overrides) -> dict:
    defaults = {
        "account_name": f"Acct-{unique_code('N')}",
        "account_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_slot_pool_payload(**overrides) -> dict:
    defaults = {
        "build_month": "2026-08",
        "vocation_group": "STANDARD",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_factory_order_payload(**overrides) -> dict:
    defaults = {
        "chassis_model": "M2_106",
        "engine_option": "DD13",
        "axle_config": "A4X2",
    }
    defaults.update(overrides)
    return defaults


def create_trade_appraisal_payload(**overrides) -> dict:
    defaults = {
        "trade_vin": unique_vin(),
        "model_year": 2023,
        "mileage": 120000,
        "condition_grade": "B",
        "base_book_value_cents": 6000000,
    }
    defaults.update(overrides)
    return defaults


def create_service_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_code": unique_code("BAY"),
        "bay_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_mobile_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": unique_code("MSU"),
        "default_travel_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(**overrides) -> dict:
    defaults = {
        "external_vin": unique_vin(),
        "concern": "customer concern",
        "promised_ready_at": "2026-08-20T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ro_labor_line_payload(**overrides) -> dict:
    defaults = {
        "line_type": "LABOR",
        "hours": 1.0,
        "description": "labor",
    }
    defaults.update(overrides)
    return defaults


def create_ro_part_line_payload(**overrides) -> dict:
    defaults = {
        "line_type": "PART",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_service_booking_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-08-05T09:00:00Z",
        "end_at": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claimed_labor_cents": 0,
        "claimed_parts_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_code("SKU"),
        "part_name": "Part",
        "list_price_cents": 1000,
        "cost_cents": 500,
        "on_hand": 10,
    }
    defaults.update(overrides)
    return defaults


def create_parts_sale_payload(**overrides) -> dict:
    defaults = {"lines": []}
    defaults.update(overrides)
    return defaults
