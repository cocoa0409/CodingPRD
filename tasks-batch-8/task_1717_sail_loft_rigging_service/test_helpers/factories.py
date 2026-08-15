"""Payload factories — one per creatable resource, input fields only (PRD §3/§4)."""
import itertools

from .constants import (
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_INSTALL_DATE,
    STANDARD_MEASUREMENT,
)

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Test Customer {_n()}",
        "email": f"customer{_n()}@example.com",
        "credit_limit_cents": DEFAULT_CREDIT_LIMIT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_boat_payload(**overrides) -> dict:
    defaults = {
        "boat_name": f"Test Boat {_n()}",
        "hull_length_m": 10.0,
        "racing_class": "NONE",
        "standing_rigging_install_date": DEFAULT_INSTALL_DATE,
        "running_rigging_hours_accumulated": 0,
    }
    defaults.update(overrides)
    return defaults


def create_measurement_sheet_payload(**overrides) -> dict:
    defaults = dict(STANDARD_MEASUREMENT)
    defaults.update(overrides)
    return defaults


def create_sail_design_payload(measurement_sheet_id, expected_boat_version, **overrides) -> dict:
    defaults = {
        "measurement_sheet_id": measurement_sheet_id,
        "cloth_tier": "CRUISE",
        "reinforcement_level": 1,
        "option_codes": [],
        "expected_boat_version": expected_boat_version,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id, boat_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "boat_id": boat_id,
        "order_kind": "NEW_SAIL",
    }
    defaults.update(overrides)
    return defaults


def create_production_job_payload(**overrides) -> dict:
    defaults = {
        "bay_code": "BAY_A",
        "scheduled_start_date": "2026-09-01",
        "scheduled_end_date": "2026-09-05",
    }
    defaults.update(overrides)
    return defaults


def create_cloth_bolt_payload(**overrides) -> dict:
    defaults = {
        "bolt_code": f"BOLT-{_n()}",
        "cloth_tier": "CRUISE",
        "total_sqm": 500.0,
        "price_per_sqm_cents": 4200,
    }
    defaults.update(overrides)
    return defaults


def create_rigging_inspection_payload(expected_boat_version, **overrides) -> dict:
    defaults = {
        "rigging_scope": "FULL",
        "expected_boat_version": expected_boat_version,
    }
    defaults.update(overrides)
    return defaults


def create_mast_service_event_payload(**overrides) -> dict:
    defaults = {
        "service_kind": "TUNE",
        "slot_start_utc": "2026-09-01T08:00:00Z",
        "slot_end_utc": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_storage_contract_payload(**overrides) -> dict:
    defaults = {
        "season_code": "WINTER_2026",
        "wash_item_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_class_certificate_payload(measurement_sheet_id, racing_class, **overrides) -> dict:
    defaults = {
        "measurement_sheet_id": measurement_sheet_id,
        "racing_class": racing_class,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
