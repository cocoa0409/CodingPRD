"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
        "season": TEST_DEFAULTS["SEASON"],
    }
    # guarantee (program_year, season) uniqueness across tests sharing a server
    defaults["program_year"] = 2026 + n
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    defaults = {"name": f"Z-Zone-{_n()}"}
    defaults.update(overrides)
    return defaults


def create_private_owner_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "name": f"Owner Org {n}",
        "contact_email": f"ops{n}@owner.example",
    }
    defaults.update(overrides)
    return defaults


def create_hydrant_payload(program_id: str, zone_id: str, **overrides) -> dict:
    defaults = {
        "hydrant_number": f"H-{_n()}",
        "program_id": program_id,
        "zone_id": zone_id,
        "ownership": "MUNICIPAL",
        "required_fire_flow_gpm": TEST_DEFAULTS["REQUIRED_FIRE_FLOW_GPM"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(hydrant_id: str, expected_hydrant_version: int, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "scheduled_date": "2026-08-10T00:00:00Z",
        "expected_hydrant_version": expected_hydrant_version,
    }
    defaults.update(overrides)
    return defaults


def record_inspection_payload(**overrides) -> dict:
    defaults = {
        "performed_date": "2026-08-10T00:00:00Z",
        "defects_found": False,
    }
    defaults.update(overrides)
    return defaults


def create_flow_test_payload(hydrant_id: str, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "window_start": "2026-08-02T10:00:00Z",
        "window_end": "2026-08-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def flow_results_payload(**overrides) -> dict:
    defaults = {
        "static_psi": TEST_DEFAULTS["STATIC_PSI"],
        "residual_psi": TEST_DEFAULTS["RESIDUAL_PSI"],
        "pitot_psi": TEST_DEFAULTS["PITOT_PSI"],
    }
    defaults.update(overrides)
    return defaults


def create_flush_sequence_payload(program_id: str, zone_id: str, hydrant_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "zone_id": zone_id,
        "hydrant_id": hydrant_id,
        "window_start": "2026-08-03T10:00:00Z",
        "window_end": "2026-08-03T12:00:00Z",
        "steps": [{"step_index": 1, "valve_tag": "V-A", "action": "OPEN"}],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(hydrant_id: str, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "category": "DISCOLORED_WATER",
    }
    defaults.update(overrides)
    return defaults


def create_outage_payload(hydrant_id: str, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "reason": "LEAK",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(hydrant_id: str, **overrides) -> dict:
    defaults = {
        "hydrant_id": hydrant_id,
        "description": "Repair work",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Part {n}",
        "unit_price_cents": 6500,
        "on_hand_qty": 100,
    }
    defaults.update(overrides)
    return defaults


def create_iso_snapshot_payload(**overrides) -> dict:
    defaults = {"weighting_profile": "MUNICIPAL_ONLY"}
    defaults.update(overrides)
    return defaults
