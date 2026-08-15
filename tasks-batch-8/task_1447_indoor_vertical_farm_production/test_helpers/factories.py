"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import DEFAULT_KALE_RECIPE

_code_seq = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_code_seq):04d}"


def create_crop_payload(**overrides) -> dict:
    defaults = {
        "crop_code": _unique("KALE"),
        "display_name": "Kale",
        "category": "LEAFY_GREEN",
        "margin_cents_per_lb": 300,
        "floor_price_cents_per_lb": 100,
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(crop_id: str, **overrides) -> dict:
    defaults = dict(DEFAULT_KALE_RECIPE)
    defaults["crop_id"] = crop_id
    defaults.update(overrides)
    return defaults


def create_water_loop_payload(**overrides) -> dict:
    defaults = {"loop_code": _unique("WL")}
    defaults.update(overrides)
    return defaults


def create_rack_payload(water_loop_id: str, **overrides) -> dict:
    defaults = {
        "rack_code": _unique("R"),
        "water_loop_id": water_loop_id,
        "zone": "Z1",
        "tower_count": 4,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(crop_id: str, tower_ids: list, **overrides) -> dict:
    defaults = {"crop_id": crop_id, "tower_ids": list(tower_ids)}
    defaults.update(overrides)
    return defaults


def create_sanitation_cycle_payload(water_loop_id: str, **overrides) -> dict:
    defaults = {
        "water_loop_id": water_loop_id,
        "scheduled_start_at": "2026-08-22T01:00:00Z",
        "scheduled_end_at": "2026-08-22T03:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(crop_id: str, **overrides) -> dict:
    defaults = {
        "retailer_name": "FreshMart",
        "crop_id": crop_id,
        "weekly_commitment_lb": 500,
        "price_per_pound_cents": 245,
        "penalty_cents_per_short_lb": 150,
        "fill_rate_threshold": 0.98,
        "week_start_day": "MONDAY",
        "start_date": "2026-08-24",
        "end_date": "2026-09-20",
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(contract_id: str, expected_contract_version: int,
                            lines: list, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "ship_date": "2026-08-24",
        "window_start_at": "2026-08-24T08:00:00Z",
        "window_end_at": "2026-08-24T20:00:00Z",
        "expected_contract_version": expected_contract_version,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    defaults = {
        "full_name": _unique("Worker"),
        "certifications": ["PACK_CREW"],
        "hourly_rate_cents": 2200,
    }
    defaults.update(overrides)
    return defaults


def create_labor_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_date": "2026-08-05",
        "role_type": "PACK_CREW",
        "start_at": "2026-08-05T07:00:00Z",
        "end_at": "2026-08-05T15:00:00Z",
        "headcount_required": 1,
        "planned_hourly_rate_cents": 2200,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(worker_id: str, expected_labor_shift_version: int) -> dict:
    return {
        "worker_id": worker_id,
        "expected_labor_shift_version": expected_labor_shift_version,
    }


def create_energy_reading_payload(**overrides) -> dict:
    defaults = {
        "scope_type": "FACILITY",
        "period_start_at": "2026-08-03T00:00:00Z",
        "period_end_at": "2026-08-24T00:00:00Z",
        "kwh_consumed": 40000.0,
        "peak_demand_kw": 480.0,
    }
    defaults.update(overrides)
    return defaults
