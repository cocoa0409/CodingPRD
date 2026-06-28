"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields (with PRD-declared defaults) are
omitted unless overridden.
"""


def create_membership_plan_payload(**overrides) -> dict:
    """Required: tier_code, monthly_fee_cents.
    Optional (PRD defaults): retail_discount_pct=0, weekly_uv_session_cap=0,
    includes_spray=true."""
    defaults = {
        "tier_code": "UNLIMITED",
        "monthly_fee_cents": 6000,
        "weekly_uv_session_cap": 0,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Required: full_name, date_of_birth, skin_type, plan_id."""
    defaults = {
        "full_name": "Test Member",
        "date_of_birth": "1990-01-01T00:00:00Z",
        "skin_type": "IV",
        "plan_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    """Required: name, kind, max_exposure_seconds.
    Optional (PRD default): turnaround_seconds=600."""
    defaults = {
        "name": "Test Bed",
        "kind": "BED",
        "max_exposure_seconds": 600,
    }
    defaults.update(overrides)
    return defaults


def create_spray_room_payload(**overrides) -> dict:
    """Required: name. Optional (PRD default): ventilation_buffer_seconds=300."""
    defaults = {
        "name": "Test Spray Room",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    """Required: guardian_name, expires_at."""
    defaults = {
        "guardian_name": "Test Guardian",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    """Required: member_id, kind, booking_mode, start_at, requested_seconds,
    plus exactly one of equipment_id (UV) or spray_room_id (SPRAY)."""
    defaults = {
        "member_id": None,
        "kind": "UV",
        "booking_mode": "RESERVATION",
        "start_at": "2026-06-01T10:00:00Z",
        "requested_seconds": 120,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    """Required: sku, name, unit_price_cents, initial_stock."""
    defaults = {
        "sku": "TEST-SKU",
        "name": "Test Product",
        "unit_price_cents": 1000,
        "initial_stock": 10,
    }
    defaults.update(overrides)
    return defaults


def create_retail_order_payload(**overrides) -> dict:
    """Required: member_id, lines (array of {product_id, quantity})."""
    defaults = {
        "member_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults
