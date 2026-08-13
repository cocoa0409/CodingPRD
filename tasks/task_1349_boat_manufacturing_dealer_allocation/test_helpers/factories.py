"""Payload factories — one per entity, input fields only.

Code-like fields get a random suffix by default so a test may call the same
factory twice without tripping the PRD's uniqueness rules; tests asserting a
specific code pass it explicitly via overrides.
"""
import uuid

from .constants import (
    CANONICAL_MODEL,
    CANONICAL_OPTION_BALLAST,
    CANONICAL_OPTION_TOWER,
)


def _suffix() -> str:
    return uuid.uuid4().hex[:6].upper()


def create_boat_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": f"SP190-{_suffix()}",
        "model_name": "Sport 190",
        "model_year": 2027,
        "base_price_cents": CANONICAL_MODEL["base_price_cents"],
        "length_feet": CANONICAL_MODEL["length_feet"],
        "production_hours": CANONICAL_MODEL["production_hours"],
    }
    defaults.update(overrides)
    return defaults


def create_option_package_payload(model_id: str, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "option_code": f"OPT-{_suffix()}",
        "name": "Option Package",
        "price_cents": CANONICAL_OPTION_TOWER["price_cents"],
        "production_hours": CANONICAL_OPTION_TOWER["production_hours"],
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "dealer_code": f"D-{_suffix()}",
        "name": "Coastal Marine",
        "region": "SE",
        "annual_allocation_quota": 5,
        "floor_plan_limit_cents": 10000000,
    }
    defaults.update(overrides)
    return defaults


def create_boat_show_event_payload(**overrides) -> dict:
    defaults = {
        "event_name": f"Show {_suffix()}",
        "region": "SE",
        "start_date": "2026-08-01",
        "end_date": "2026-08-15",
        "surge_deposit_rate": 0.05,
        "allocation_boost": 1,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(**overrides) -> dict:
    defaults = {
        "plant_line_code": f"L-{_suffix()}",
        "season": "PEAK",
        "build_week_start": "2026-08-03",
        "build_week_end": "2026-08-10",
        "option_change_cutoff_at": "2026-08-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_build_slot_payload(run_id: str, **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "slot_code": f"S-{_suffix()}",
        "capacity_hours": 200,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_order_payload(dealer_id: str, model_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "model_id": model_id,
        "source": "RETAIL",
        "deposit_paid_cents": 257500,
        "option_package_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_amend_order_payload(expected_order_version: int, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_hull_payload(order_id: str, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def create_update_dealer_payload(expected_dealer_version: int, **overrides) -> dict:
    defaults = {"expected_dealer_version": expected_dealer_version}
    defaults.update(overrides)
    return defaults


def create_curtailment_payload(expected_dealer_version: int, amount_cents: int) -> dict:
    return {
        "expected_dealer_version": expected_dealer_version,
        "amount_cents": amount_cents,
    }


def create_warranty_registration_payload(
    hull_id: str, dealer_id: str, retail_sale_date: str, **overrides
) -> dict:
    defaults = {
        "hull_id": hull_id,
        "dealer_id": dealer_id,
        "retail_sale_date": retail_sale_date,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(registration_id: str, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "defect_description": "gel coat crazing",
        "labor_hours": 1.0,
        "parts_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_recall_campaign_payload(**overrides) -> dict:
    defaults = {
        "campaign_code": f"RC-{_suffix()}",
        "severity": "SAFETY_STOP",
        "model_code": "SP190",
        "model_year": 2027,
        "hin_serial_start": 1,
        "hin_serial_end": 5,
    }
    defaults.update(overrides)
    return defaults
