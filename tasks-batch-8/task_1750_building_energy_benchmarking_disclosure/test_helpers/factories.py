"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import CYCLE_DEFAULTS

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_owner_payload(**overrides) -> dict:
    n = _next()
    defaults = {"name": f"Test Owner {n}", "contact_email": f"owner{n}@example.com"}
    defaults.update(overrides)
    return defaults


def create_verifier_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Test Verifier {n}",
        "license_number": f"LIC-{n:04d}",
        "accredited": True,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = dict(CYCLE_DEFAULTS)
    defaults["covered_property_types"] = list(CYCLE_DEFAULTS["covered_property_types"])
    defaults["performance_standards"] = [dict(s) for s in CYCLE_DEFAULTS["performance_standards"]]
    defaults.update(overrides)
    return defaults


def create_building_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "address": f"{n} Main St",
        "gross_floor_area_sqft": 50000,
        "property_type": "OFFICE",
    }
    defaults.update(overrides)
    return defaults


def create_tenant_unit_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "unit_label": f"U{n}",
        "floor_area_sqft": 10000,
        "space_type": "OFFICE",
        "occupied": True,
    }
    defaults.update(overrides)
    return defaults


def create_utility_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {"account_number": f"ACCT-{n:04d}", "commodity": "ELECTRICITY"}
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2027-01-01T00:00:00Z",
        "period_end": "2028-01-01T00:00:00Z",
        "consumption_value": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_benchmark_report_payload(building_id: str, cycle_id: str, **overrides) -> dict:
    defaults = {"building_id": building_id, "cycle_id": cycle_id}
    defaults.update(overrides)
    return defaults


def create_verification_record_payload(verifier_id: str, **overrides) -> dict:
    defaults = {"verifier_id": verifier_id}
    defaults.update(overrides)
    return defaults


def create_anomaly_flag_payload(**overrides) -> dict:
    defaults = {"detail": "Officer desk audit finding"}
    defaults.update(overrides)
    return defaults


def create_exemption_request_payload(cycle_id: str, **overrides) -> dict:
    defaults = {
        "cycle_id": cycle_id,
        "request_type": "EXEMPTION",
        "reason": "Building qualifies for relief this cycle",
    }
    defaults.update(overrides)
    return defaults


def grant_consent_payload(**overrides) -> dict:
    defaults = {"valid_from": "2027-01-01", "valid_to": "2027-12-31"}
    defaults.update(overrides)
    return defaults
