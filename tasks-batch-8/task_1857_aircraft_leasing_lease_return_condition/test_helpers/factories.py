"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_aircraft_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "msn": f"MSN-T{i:04d}",
        "model": TEST_DEFAULTS["MODEL"],
        "manufacture_date": TEST_DEFAULTS["MANUFACTURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_lessee_payload(**overrides) -> dict:
    i = _n()
    defaults = {"legal_name": f"Test Air {i}"}
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Iris Nspect {i}",
        "license_number": f"LIC-T{i:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "aircraft_id": overrides.pop("aircraft_id", None),
        "lessee_id": overrides.pop("lessee_id", None),
        "start_date": TEST_DEFAULTS["LEASE_START_DATE"],
        "end_date": TEST_DEFAULTS["LEASE_END_DATE"],
        "monthly_rent_cents": TEST_DEFAULTS["MONTHLY_RENT_CENTS"],
        "reserve_rate_per_fh_cents": TEST_DEFAULTS["RESERVE_RATE_PER_FH_CENTS"],
        "reserve_rate_per_fc_cents": TEST_DEFAULTS["RESERVE_RATE_PER_FC_CENTS"],
        "monthly_hour_cap": TEST_DEFAULTS["MONTHLY_HOUR_CAP"],
    }
    defaults = {k: v for k, v in defaults.items() if v is not None}
    defaults.update(overrides)
    return defaults


def create_utilization_report_payload(**overrides) -> dict:
    defaults = {
        "period_month": TEST_DEFAULTS["PERIOD_MONTH"],
        "flight_hours": 100.0,
        "flight_cycles": 20,
    }
    defaults.update(overrides)
    return defaults


def create_reserve_claim_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "maintenance_event_ref": f"MX-EVT-{i:04d}",
        "claimed_amount_cents": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "doc_type": "BIRTH_RECORD",
        "doc_reference": f"DOC-T{i:04d}",
    }
    defaults.update(overrides)
    return defaults


def create_transition_slot_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-09-10",
        "window_end": "2026-09-20",
    }
    defaults.update(overrides)
    return defaults


def create_novation_request_payload(**overrides) -> dict:
    defaults = {
        "request_type": "NOVATION",
        "proposed_lessee_id": overrides.pop("proposed_lessee_id", None),
    }
    defaults = {k: v for k, v in defaults.items() if v is not None}
    defaults.update(overrides)
    return defaults


def create_default_case_payload(**overrides) -> dict:
    defaults = {
        "reason": "rent arrears",
        "cure_period_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "inspector_id": overrides.pop("inspector_id", None),
        "booking_date": "2026-08-01",
    }
    defaults = {k: v for k, v in defaults.items() if v is not None}
    defaults.update(overrides)
    return defaults
