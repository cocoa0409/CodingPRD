"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import (
    DEFAULT_AREA,
    DEFAULT_FISHERY,
    DEFAULT_OPENING_CLOSES,
    DEFAULT_OPENING_OPENS,
    DEFAULT_PERMIT_VALID_FROM,
    DEFAULT_PERMIT_VALID_TO,
    DEFAULT_PORT,
    DEFAULT_SEASON_YEAR,
    DEFAULT_TAC_POUNDS,
)

_license_counter = itertools.count(1)


def next_license_number() -> str:
    return f"LIC-{next(_license_counter):05d}"


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "vessel_name": "FV Aurora",
        "license_number": next_license_number(),
        "home_port": DEFAULT_PORT,
        "length_ft": 58,
        "observer_coverage_class": "PARTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "fishery_code": DEFAULT_FISHERY,
        "gear_type": "LONGLINE",
        "valid_from": DEFAULT_PERMIT_VALID_FROM,
        "valid_to": DEFAULT_PERMIT_VALID_TO,
    }
    defaults.update(overrides)
    return defaults


def create_quota_holding_payload(**overrides) -> dict:
    defaults = {
        "fishery_code": DEFAULT_FISHERY,
        "season_year": DEFAULT_SEASON_YEAR,
        "initial_pounds": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_season_opening_payload(**overrides) -> dict:
    defaults = {
        "fishery_code": DEFAULT_FISHERY,
        "area_code": DEFAULT_AREA,
        "opens_at": DEFAULT_OPENING_OPENS,
        "closes_at": DEFAULT_OPENING_CLOSES,
        "tac_pounds": DEFAULT_TAC_POUNDS,
    }
    defaults.update(overrides)
    return defaults


def create_fishing_trip_payload(**overrides) -> dict:
    defaults = {
        "planned_departure_utc": "2026-08-10T06:00:00Z",
        "planned_return_utc": "2026-08-12T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_catch_report_payload(**overrides) -> dict:
    defaults = {
        "fishery_code": DEFAULT_FISHERY,
        "report_type": "HARVEST",
        "reported_lbs": 4000,
        "reported_at": "2026-08-11T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_landing_declaration_payload(**overrides) -> dict:
    defaults = {
        "port_code": DEFAULT_PORT,
        "lines": [{"fishery_code": DEFAULT_FISHERY, "declared_lbs": 4000}],
    }
    defaults.update(overrides)
    return defaults


def create_quota_transfer_payload(**overrides) -> dict:
    defaults = {
        "fishery_code": DEFAULT_FISHERY,
        "season_year": DEFAULT_SEASON_YEAR,
        "pounds": 5000,
        "price_per_lb_cents": 400,
    }
    defaults.update(overrides)
    return defaults


def create_observer_payload(**overrides) -> dict:
    defaults = {
        "observer_name": "Obs One",
        "certification_level": "B",
        "home_base": DEFAULT_PORT,
    }
    defaults.update(overrides)
    return defaults


def create_assign_observer_payload(**overrides) -> dict:
    defaults = {
        "coverage_from": "2026-08-10T00:00:00Z",
        "coverage_to": "2026-08-12T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_crew_contract_payload(**overrides) -> dict:
    defaults = {
        "crew_name": "Alice",
        "share_points": 1,
        "joined_at": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_expense_payload(**overrides) -> dict:
    defaults = {
        "category": "FUEL",
        "amount_cents": 120000,
        "incurred_at": "2026-08-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(**overrides) -> dict:
    defaults = {"gross_revenue_cents": 1000000}
    defaults.update(overrides)
    return defaults


def create_gear_asset_payload(**overrides) -> dict:
    defaults = {"gear_type": "LONGLINE", "units_total": 4}
    defaults.update(overrides)
    return defaults


def create_gear_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "LOSS",
        "units": 1,
        "occurred_at": "2026-08-11T05:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vms_ping_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-08-10T02:00:00Z",
        "latitude": 59.64,
        "longitude": -151.55,
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(**overrides) -> dict:
    defaults = {
        "violation_type": "OVER_QUOTA",
        "details": "logbook discrepancy",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
