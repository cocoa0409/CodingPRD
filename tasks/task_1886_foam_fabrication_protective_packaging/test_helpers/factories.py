"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Optional

from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Widgets",
        "account_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "foam_family": "PE",
        "density_pcf": 1.7,
        "ild_lb_25": TEST_DEFAULTS["MATERIAL_ILD_LB_25"],
        "sheet_length_in": TEST_DEFAULTS["SHEET_LENGTH_IN"],
        "sheet_width_in": TEST_DEFAULTS["SHEET_WIDTH_IN"],
        "sheet_thickness_in": TEST_DEFAULTS["SHEET_THICKNESS_IN"],
        "cost_per_board_ft_cents": TEST_DEFAULTS["COST_PER_BOARD_FT_CENTS"],
        "recyclable": True,
        "scrap_credit_per_lb_cents": TEST_DEFAULTS["SCRAP_CREDIT_PER_LB_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_package_spec_payload(customer_id: str, material_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "material_id": material_id,
        "part_name": "Widget Tray",
        "part_length_in": TEST_DEFAULTS["PART_LENGTH_IN"],
        "part_width_in": TEST_DEFAULTS["PART_WIDTH_IN"],
        "product_weight_lb": TEST_DEFAULTS["PRODUCT_WEIGHT_LB"],
        "required_drop_height_in": TEST_DEFAULTS["REQUIRED_DROP_HEIGHT_IN"],
        "max_fragility_g": TEST_DEFAULTS["MAX_FRAGILITY_G"],
    }
    defaults.update(overrides)
    return defaults


def create_cut_program_payload(
    package_spec_id: str,
    expected_package_spec_version: int,
    method: str = "DIE_CUT",
    machine_seconds_per_part: Optional[int] = None,
    supersedes_cut_program_id: Optional[str] = None,
) -> dict:
    payload = {
        "package_spec_id": package_spec_id,
        "method": method,
        "expected_package_spec_version": expected_package_spec_version,
    }
    if machine_seconds_per_part is not None:
        payload["machine_seconds_per_part"] = machine_seconds_per_part
    if supersedes_cut_program_id is not None:
        payload["supersedes_cut_program_id"] = supersedes_cut_program_id
    return payload


def create_tooling_payload(cut_program_id: str, **overrides) -> dict:
    defaults = {
        "cut_program_id": cut_program_id,
        "die_cost_cents": TEST_DEFAULTS["DIE_COST_CENTS"],
        "amortization_qty": TEST_DEFAULTS["AMORTIZATION_QTY"],
        "lead_time_days": TEST_DEFAULTS["LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_drop_test_payload(
    package_spec_id: str,
    scheduled_start: str,
    scheduled_end: str,
    **overrides,
) -> dict:
    defaults = {
        "package_spec_id": package_spec_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "drop_height_in": TEST_DEFAULTS["REQUIRED_DROP_HEIGHT_IN"],
        "orientation": "FLAT",
    }
    defaults.update(overrides)
    return defaults


def create_production_order_payload(
    package_spec_id: str, cut_program_id: str, qty: int, **overrides,
) -> dict:
    defaults = {
        "package_spec_id": package_spec_id,
        "cut_program_id": cut_program_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_confirm_payload(
    machine_id: str, window_start: str, window_end: str,
) -> dict:
    return {
        "machine_id": machine_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def create_inventory_program_payload(
    customer_id: str, package_spec_id: str, **overrides,
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "package_spec_id": package_spec_id,
        "pricing_mode": "CURRENT",
        "max_stock_qty": 1000,
        "reorder_point_qty": 200,
        "min_release_qty": 50,
    }
    defaults.update(overrides)
    return defaults


def create_release_order_payload(
    inventory_program_id: str,
    qty: int,
    requested_ship_date: str = "2026-08-10T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "inventory_program_id": inventory_program_id,
        "qty": qty,
        "requested_ship_date": requested_ship_date,
    }
    defaults.update(overrides)
    return defaults


def create_scrap_batch_payload(
    production_order_id: str, gross_weight_lb: float, contamination_pct: float,
    **overrides,
) -> dict:
    defaults = {
        "production_order_id": production_order_id,
        "gross_weight_lb": gross_weight_lb,
        "contamination_pct": contamination_pct,
    }
    defaults.update(overrides)
    return defaults
