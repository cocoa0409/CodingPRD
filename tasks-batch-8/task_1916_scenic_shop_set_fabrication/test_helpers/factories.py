"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import (
    STANDARD_SHOP_PAYLOAD,
    STD_BUILD_START_AT,
    STD_CONTACT_EMAIL,
    STD_COMPANY_NAME,
    STD_LOAD_IN_AT,
    STD_SHOW_TITLE,
    STD_STRIKE_AT,
    STD_VENUE,
)


def create_shop_payload(**overrides) -> dict:
    defaults = dict(STANDARD_SHOP_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "shop_id": "",
        "company_name": STD_COMPANY_NAME,
        "contact_email": STD_CONTACT_EMAIL,
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_design_package_payload(**overrides) -> dict:
    defaults = {
        "client_id": "",
        "show_title": STD_SHOW_TITLE,
        "venue": STD_VENUE,
        "load_in_at": STD_LOAD_IN_AT,
        "strike_at": STD_STRIKE_AT,
    }
    defaults.update(overrides)
    return defaults


def create_takeoff_payload(**overrides) -> dict:
    defaults = {
        "design_package_id": "",
        "labor_hours_est": 100,
    }
    defaults.update(overrides)
    return defaults


def create_takeoff_line_payload(**overrides) -> dict:
    defaults = {
        "takeoff_id": "",
        "expected_takeoff_version": 1,
        "material_code": "LUMBER_4X8",
        "quantity": 1,
        "source": "PURCHASE",
        "unit_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    """Default is a ROM bid (most tests only need a priced bid)."""
    defaults = {
        "client_id": "",
        "design_package_id": "",
        "pricing_variant": "ROM",
        "has_automation_scope": False,
        "bays_required": 1,
        "build_start_at": STD_BUILD_START_AT,
        "validity_days": 30,
        "floor_area_sqft": 100,
        "complexity_class": "A_SIMPLE",
        "estimated_crew_hours": 100,
    }
    defaults.update(overrides)
    return defaults


def create_engineering_review_payload(**overrides) -> dict:
    defaults = {
        "production_id": "",
        "scope": "STRUCTURAL",
        "design_load_lb": 4000,
        "member_capacity_lb": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_finish_sample_payload(**overrides) -> dict:
    defaults = {
        "production_id": "",
        "finish_code": "SCUFF_BRICK_RED",
        "texture_ref": "tex_v1",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(**overrides) -> dict:
    defaults = {
        "production_id": "",
        "expected_production_version": 1,
        "new_drawing_revision": 2,
        "delta_materials_cents": 0,
        "delta_labor_hours": 0,
        "delta_load_in_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_bay_reservation_payload(**overrides) -> dict:
    defaults = {
        "production_id": "",
        "bay_slot": 1,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-26T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_stock_item_payload(**overrides) -> dict:
    defaults = {
        "shop_id": "",
        "material_code": "LUMBER_4X8",
        "condition_grade": "A",
        "quantity_on_hand": 10,
        "replacement_cost_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_stock_adjust_payload(**overrides) -> dict:
    defaults = {
        "delta_quantity": 0,
        "expected_stock_item_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_transport_plan_payload(**overrides) -> dict:
    defaults = {
        "production_id": "",
        "truck_count": 2,
        "install_crew_hours": 16,
        "depart_at": "2026-09-11T00:00:00Z",
        "arrive_at": "2026-09-12T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
