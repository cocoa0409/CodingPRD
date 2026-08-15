"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import CLOCK_T0800


def create_unit_payload(**overrides) -> dict:
    defaults = {"unit_code": "U1", "display_name": "Unit One"}
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    defaults = {"unit_id": None, "bed_code": "B1", "bed_kind": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_placement_demand_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "required_bed_kind": "STANDARD",
        "urgency_tier": "URGENT",
        "needed_by": "2026-08-01T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_clean_request_payload(**overrides) -> dict:
    defaults = {"bed_id": None, "clean_type": "ROUTINE"}
    defaults.update(overrides)
    return defaults


def assign_request_payload(**overrides) -> dict:
    defaults = {"staff_id": None}
    defaults.update(overrides)
    return defaults


def create_staff_payload(**overrides) -> dict:
    defaults = {
        "employee_code": "T1",
        "display_name": "Tech One",
        "capabilities": ["CLEAN"],
        "certifications": [],
    }
    defaults.update(overrides)
    return defaults


def create_quality_audit_payload(**overrides) -> dict:
    defaults = {
        "clean_request_id": None,
        "audit_method": "ATP_SWAB",
        "rlu_reading": 100,
    }
    defaults.update(overrides)
    return defaults


def create_supply_item_payload(**overrides) -> dict:
    defaults = {
        "item_code": "DISINFECTANT",
        "display_name": "Disinfectant",
        "initial_on_hand": 100,
        "reorder_threshold": 10,
    }
    defaults.update(overrides)
    return defaults


def create_outbreak_event_payload(**overrides) -> dict:
    defaults = {"unit_id": None, "pathogen_class": "C_DIFF"}
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(**overrides) -> dict:
    defaults = {
        "bed_id": None,
        "start_at": "2026-08-01T10:00:00Z",
        "end_at": "2026-08-01T11:00:00Z",
        "reason": "hvac",
    }
    defaults.update(overrides)
    return defaults


def create_clean_standard_payload(**overrides) -> dict:
    defaults = {
        "clean_type": "ROUTINE",
        "base_minutes": 45,
        "outbreak_multiplier_bps": 15000,
        "atp_rlu_threshold": 250,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = CLOCK_T0800) -> dict:
    return {"to_iso8601": to_iso8601}
