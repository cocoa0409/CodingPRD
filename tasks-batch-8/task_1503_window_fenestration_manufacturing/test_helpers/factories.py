"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import (
    A050_PAYLOAD,
    GP1_PAYLOAD,
    GP3_PAYLOAD,
    MN_RULE_PAYLOAD,
    ORDER_DATE,
    V200_PAYLOAD,
)


def create_dealer_payload(**overrides) -> dict:
    defaults = {"name": "NorthStar", "ship_to_state_code": "MN"}
    defaults.update(overrides)
    return defaults


def create_catalog_series_payload(**overrides) -> dict:
    defaults = dict(V200_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_a050_series_payload(**overrides) -> dict:
    defaults = dict(A050_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_glass_package_payload(**overrides) -> dict:
    defaults = dict(GP1_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_gp3_package_payload(**overrides) -> dict:
    defaults = dict(GP3_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_energy_code_rule_payload(**overrides) -> dict:
    defaults = dict(MN_RULE_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_order_payload(dealer_id: str, **overrides) -> dict:
    defaults = {"dealer_id": dealer_id, "order_date": ORDER_DATE}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(series_id: str, glass_package_id: str, **overrides) -> dict:
    defaults = {
        "series_id": series_id,
        "glass_package_id": glass_package_id,
        "shape": "RECTANGLE",
        "width_in": 40,
        "height_in": 60,
        "quantity": 1,
        "grid_style": "NONE",
        "hardware_finish": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(**overrides) -> dict:
    defaults = {
        "wave_date": "2026-09-01T00:00:00Z",
        "capacity_units": 10,
        "capacity_glass_sqft": 500,
    }
    defaults.update(overrides)
    return defaults


def create_rack_payload(**overrides) -> dict:
    defaults = {"rack_code": "R1", "slot_capacity": 5}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "load_date": "2026-09-02T00:00:00Z",
        "ship_date": "2026-09-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(order_id: str, order_line_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "order_line_id": order_line_id,
        "component": "FRAME",
        "coverage_variant": "COMPONENT",
        "failure_date": "2027-09-01T00:00:00Z",
        "description": "failure reported",
    }
    defaults.update(overrides)
    return defaults


def create_approve_repair_part_payload(**overrides) -> dict:
    defaults = {
        "remedy": "REPAIR_PART",
        "part_sku": "CRANK-7",
        "quantity": 1,
        "carrier": "PARCEL",
    }
    defaults.update(overrides)
    return defaults
