"""Payload factories — one per entity, input fields only."""
from typing import Any, Dict

DEFAULTS = {
    "SEASON_YEAR": 2026,
    "DIESEL_CENTS": 300,
    "GROWER_NAME": "Test Grower",
    "STATE_CODE": "KS",
    "CROP": "WHEAT",
    "RATE_BASIS": "PER_ACRE",
    "RATE_CENTS_PER_ACRE": 3200,
    "RATE_CENTS_PER_BUSHEL": 0,
    "COMMITTED_ACRES": 100,
    "PLANNED_START": "2026-08-05",
    "PLANNED_END": "2026-08-06",
    "PLANNED_ACRES": 100,
    "SEQUENCE_INDEX": 1,
    "MACHINE_KIND": "COMBINE",
    "MACHINE_LABEL": "Combine-01",
    "DAILY_CAPACITY_ACRES": 200,
    "CREW_NAME": "Test Hand",
    "VISA_TYPE": "US_CITIZEN",
    "VISA_EXPIRY": "2099-01-01",
    "HOURLY_RATE_CENTS": 2000,
    "ASSIGN_START": "2026-08-05",
    "ASSIGN_END": "2026-08-07",
    "DELIVERED_AT": "2026-08-06T12:00:00Z",
    "GROSS_BUSHELS": 1000,
    "MOISTURE_PCT": 14.0,
    "SITE_NAME": "Motel 6",
    "TOTAL_BEDS": 2,
    "STAY_START": "2026-08-05",
    "STAY_END": "2026-08-08",
    "BED_COUNT": 1,
}


def create_season_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "season_year": DEFAULTS["SEASON_YEAR"],
        "diesel_baseline_per_gallon_cents": DEFAULTS["DIESEL_CENTS"],
        "current_diesel_per_gallon_cents": DEFAULTS["DIESEL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "grower_name": DEFAULTS["GROWER_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "crop": DEFAULTS["CROP"],
        "rate_basis": DEFAULTS["RATE_BASIS"],
        "rate_cents_per_acre": DEFAULTS["RATE_CENTS_PER_ACRE"],
        "rate_cents_per_bushel": DEFAULTS["RATE_CENTS_PER_BUSHEL"],
        "committed_acres": DEFAULTS["COMMITTED_ACRES"],
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "planned_start_date": DEFAULTS["PLANNED_START"],
        "planned_end_date": DEFAULTS["PLANNED_END"],
        "planned_acres": DEFAULTS["PLANNED_ACRES"],
        "sequence_index": DEFAULTS["SEQUENCE_INDEX"],
    }
    defaults.update(overrides)
    return defaults


def create_machine_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "machine_kind": DEFAULTS["MACHINE_KIND"],
        "label": DEFAULTS["MACHINE_LABEL"],
        "daily_capacity_acres": DEFAULTS["DAILY_CAPACITY_ACRES"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": DEFAULTS["CREW_NAME"],
        "visa_type": DEFAULTS["VISA_TYPE"],
        "visa_expiry_date": DEFAULTS["VISA_EXPIRY"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_machine_assignment_payload(route_stop_id: str, machine_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "route_stop_id": route_stop_id,
        "machine_id": machine_id,
        "assigned_start_date": DEFAULTS["ASSIGN_START"],
        "assigned_end_date": DEFAULTS["ASSIGN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_ticket_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "delivered_at": DEFAULTS["DELIVERED_AT"],
        "gross_bushels": DEFAULTS["GROSS_BUSHELS"],
        "moisture_pct": DEFAULTS["MOISTURE_PCT"],
        "used_our_trucks": False,
    }
    defaults.update(overrides)
    return defaults


def create_lodging_site_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_name": DEFAULTS["SITE_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "total_beds": DEFAULTS["TOTAL_BEDS"],
    }
    defaults.update(overrides)
    return defaults


def create_lodging_reservation_payload(crew_member_id: str, lodging_site_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "crew_member_id": crew_member_id,
        "lodging_site_id": lodging_site_id,
        "stay_start_date": DEFAULTS["STAY_START"],
        "stay_end_date": DEFAULTS["STAY_END"],
        "bed_count": DEFAULTS["BED_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def issue_settlement_payload(expected_contract_version: int) -> Dict[str, Any]:
    return {"expected_contract_version": expected_contract_version}


def close_season_payload(expected_season_version: int) -> Dict[str, Any]:
    return {"expected_season_version": expected_season_version}


def resolve_settlement_payload(resolution_note: str = "adjusted") -> Dict[str, Any]:
    return {"resolution_note": resolution_note}
