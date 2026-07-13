"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_SEASON_START,
    DEFAULT_SEASON_END,
    DEFAULT_PUMPOUT_INTERVAL_DAYS,
)

_REG_COUNTER = {"n": 0}


def _next_reg() -> str:
    _REG_COUNTER["n"] += 1
    return f"REG-{_REG_COUNTER['n']:05d}"


def create_marina_payload(**overrides) -> dict:
    defaults = {
        "name": "Cove Marina",
        "season_start_date": DEFAULT_SEASON_START,
        "season_end_date": DEFAULT_SEASON_END,
        "liveaboard_cap": 2,
        "pumpout_interval_days": DEFAULT_PUMPOUT_INTERVAL_DAYS,
    }
    defaults.update(overrides)
    return defaults


def create_berth_payload(marina_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "berth_type": "SLIP",
        "size_class": "MEDIUM",
        "max_length_ft": 40,
    }
    defaults.update(overrides)
    return defaults


def create_boater_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Boater",
        "email": "boater@example.com",
        "residency_status": "RESIDENT",
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(boater_id, **overrides) -> dict:
    defaults = {
        "boater_id": boater_id,
        "name": "Test Vessel",
        "length_ft": 30,
        "registration_number": _next_reg(),
        "registration_expiry_date": "2026-12-31",
        "has_holding_tank": False,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(marina_id, boater_id, vessel_id, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "boater_id": boater_id,
        "vessel_id": vessel_id,
        "requested_berth_type": "SLIP",
        "requested_size_class": "MEDIUM",
        "season_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_pumpout_record_payload(pumpout_date, **overrides) -> dict:
    defaults = {"pumpout_date": pumpout_date}
    defaults.update(overrides)
    return defaults


def create_derelict_report_payload(vessel_id, **overrides) -> dict:
    defaults = {"vessel_id": vessel_id, "reason": "abandoned vessel"}
    defaults.update(overrides)
    return defaults


def create_ramp_pass_payload(boater_id, vessel_id, **overrides) -> dict:
    defaults = {
        "boater_id": boater_id,
        "vessel_id": vessel_id,
        "pass_type": "SEASONAL",
        "valid_from_date": DEFAULT_SEASON_START,
        "valid_to_date": DEFAULT_SEASON_END,
    }
    defaults.update(overrides)
    return defaults


def create_lottery_round_payload(marina_id, berth_ids, **overrides) -> dict:
    defaults = {
        "marina_id": marina_id,
        "season_year": 2026,
        "berth_type": "SLIP",
        "entry_open_date": "2026-04-01",
        "entry_close_date": "2026-04-10",
        "berth_ids": berth_ids,
    }
    defaults.update(overrides)
    return defaults


def create_lottery_entry_payload(round_id, boater_id, vessel_id, **overrides) -> dict:
    defaults = {"round_id": round_id, "boater_id": boater_id, "vessel_id": vessel_id}
    defaults.update(overrides)
    return defaults
