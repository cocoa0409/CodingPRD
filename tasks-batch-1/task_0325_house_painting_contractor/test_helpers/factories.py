"""Payload factories — one per entity, input fields only."""
from .constants import (
    PRODUCT_PRICE_PER_GALLON_CENTS,
    PRODUCT_COVERAGE_SQFT_PER_GALLON_PER_COAT,
)


def create_paint_product_payload(**overrides) -> dict:
    """PaintProduct create body. `active` is optional (defaults true server-side)."""
    defaults = {
        "name": "PremiumMatte White",
        "surface_kind": "INTERIOR",
        "finish_type": "FLAT",
        "price_per_gallon_cents": PRODUCT_PRICE_PER_GALLON_CENTS,
        "coverage_sqft_per_gallon_per_coat": PRODUCT_COVERAGE_SQFT_PER_GALLON_PER_COAT,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    """CrewMember create body. `active` optional (defaults true)."""
    defaults = {
        "full_name": "Pat Painter",
        "skill_level": "MASTER",
        "daily_rate_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "name": "AirlessSprayer-A",
        "equipment_kind": "SPRAYER",
        "total_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_weather_window_payload(**overrides) -> dict:
    defaults = {
        "window_date": "2026-03-20",
        "forecast_temp_f": 60,
        "precipitation_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    """Project create body. `deposit_pct` and `warranty_months` are optional."""
    defaults = {
        "customer_id": "cust-1",
        "site_address": "1 Oak St",
        "scope": "INTERIOR",
    }
    defaults.update(overrides)
    return defaults


def create_surface_payload(project_id: str, paint_product_id: str, **overrides) -> dict:
    """Surface create body. project_id + paint_product_id are required FKs."""
    defaults = {
        "project_id": project_id,
        "label": "Bedroom",
        "surface_kind": "INTERIOR",
        "area_sqft": 120,
        "coats": 1,
        "prep_level": "LIGHT",
        "paint_product_id": paint_product_id,
    }
    defaults.update(overrides)
    return defaults


def create_color_selection_payload(surface_id: str, **overrides) -> dict:
    defaults = {
        "surface_id": surface_id,
        "color_code": "SW-7005",
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id: str, expected_project_version: int,
                                 action: str, **overrides) -> dict:
    """ChangeOrder create body. expected_project_version is non-optional (OCC)."""
    defaults = {
        "project_id": project_id,
        "expected_project_version": expected_project_version,
        "reason": "scope change",
        "action": action,
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(project_id: str, crew_member_id: str,
                                   start_date: str, end_date: str, **overrides) -> dict:
    """CrewAssignment create body. equipment_id and requires_exterior_weather optional."""
    defaults = {
        "project_id": project_id,
        "crew_member_id": crew_member_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(project_id: str, kind: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(project_id: str, surface_id: str,
                                  filed_at: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "surface_id": surface_id,
        "description": "touch-up needed",
        "filed_at": filed_at,
    }
    defaults.update(overrides)
    return defaults
