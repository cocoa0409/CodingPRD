"""Payload factories — one per creatable resource, input fields only.

Globally unique registry keys (dot_number, state_code, station_code, vin,
device_serial) default to counter-stamped values so multiple creations inside
one test never collide unless a test deliberately reuses one.
"""
import itertools

from .constants import (
    CLOCK_START_ISO,
    DEFAULT_CREDENTIAL_SETS,
    DEFAULT_GVWR_LBS,
    DEFAULT_SUB_END,
    DEFAULT_SUB_START,
)

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_carrier_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "dot_number": f"9{n:05d}",
        "legal_name": f"Test Carrier {n}",
    }
    defaults.update(overrides)
    return defaults


def create_config_payload(**overrides) -> dict:
    n = _next()
    # Two-letter unique codes: AA, AB, AC, ... (wraps after 676 creations).
    defaults = {"state_code": f"{chr(65 + (n // 26) % 26)}{chr(65 + n % 26)}"}
    defaults.update(overrides)
    return defaults


def create_station_payload(state_program_config_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "state_program_config_id": state_program_config_id,
        "station_code": f"ST-{n:04d}",
        "station_type": "FIXED_SCALE",
        "supported_channel": "BOTH",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(carrier_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "carrier_id": carrier_id,
        "vin": f"VIN-{n:06d}",
        "plate_number": f"P-{n:04d}",
        "plate_state": "CA",
        "home_state_code": "CA",
        "gvwr_lbs": DEFAULT_GVWR_LBS,
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(vehicle_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "vehicle_id": vehicle_id,
        "device_type": "TRANSPONDER",
        "device_serial": f"SN-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(carrier_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "service_start_date": DEFAULT_SUB_START,
        "service_end_date": DEFAULT_SUB_END,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(carrier_id, expected_carrier_version, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "iss_score": 30,
        "safety_rating": "SATISFACTORY",
        "source": "FMCSA_FEED",
        "effective_date": CLOCK_START_ISO[:10],
        "expected_carrier_version": expected_carrier_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(vehicle_id, station_id, approach_at, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "station_id": station_id,
        "approach_at": approach_at,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(bypass_event_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "bypass_event_id": bypass_event_id,
        "reason": f"Dispute reason {n}",
        "claimed_credit_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_override_payload(carrier_id, expected_carrier_version, **overrides) -> dict:
    n = _next()
    defaults = {
        "carrier_id": carrier_id,
        "reason": f"Waiver justification {n}",
        "start_date": "2026-09-01",
        "end_date": "2026-10-01",
        "expected_carrier_version": expected_carrier_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(carrier_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "carrier_id": carrier_id,
        "vehicle_id": vehicle_id,
        "inspection_level": "LEVEL_1",
        "inspected_at": CLOCK_START_ISO,
        "violations_found": 0,
    }
    defaults.update(overrides)
    return defaults


def default_config_fields() -> dict:
    """Explicit full rule-field set used by decision-engine fixtures."""
    return {
        "requires_weight_clearance": True,
        "random_pull_in_rate_bps": 0,
        "bypass_rate_cap_bps": 10000,
        "credential_sets_required": list(DEFAULT_CREDENTIAL_SETS),
    }
