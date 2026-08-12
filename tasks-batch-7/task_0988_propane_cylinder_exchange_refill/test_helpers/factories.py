"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
import itertools

from .constants import POLICY_P, TEST_DEFAULTS

_serial_counter = itertools.count(1)


def _next_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{next(_serial_counter):06d}"


def create_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Site",
        "cage_capacity_cylinders": TEST_DEFAULTS["CAGE_CAPACITY"],
        "par_level_full": TEST_DEFAULTS["PAR_LEVEL_FULL"],
        "commission_rate_bps": TEST_DEFAULTS["COMMISSION_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_pricing_policy_payload(site_id: str, expected_site_version: int, **overrides) -> dict:
    defaults = dict(POLICY_P)
    defaults.update({
        "site_id": site_id,
        "expected_site_version": expected_site_version,
    })
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    n = next(_serial_counter)
    defaults = {
        "name": f"Driver {n}",
        "license_number": f"CDL-{n:06d}",
        "dot_medical_expires_on": "2027-01-01",
        "vehicle_max_payload_lbs": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    n = next(_serial_counter)
    defaults = {
        "name": f"Technician {n}",
        "cert_level": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_cylinder_payload(**overrides) -> dict:
    defaults = {
        "serial_number": _next_serial("CYL"),
        "owner_kind": "FLEET",
        "water_capacity_lbs": TEST_DEFAULTS["WATER_CAPACITY_LBS"],
        "tare_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"],
        "manufacture_date": TEST_DEFAULTS["MANUFACTURE_DATE"],
        "initial_fill": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_exchange_order_payload(site_id: str, **overrides) -> dict:
    defaults = {"site_id": site_id}
    defaults.update(overrides)
    return defaults


def create_refill_ticket_payload(site_id: str, cylinder_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "cylinder_id": cylinder_id,
        "pre_weight_lbs": TEST_DEFAULTS["TARE_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_record_payload(cylinder_id: str, **overrides) -> dict:
    defaults = {
        "cylinder_id": cylinder_id,
        "method": "VISUAL",
        "outcome": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_leak_report_payload(site_id: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "severity": "MINOR",
    }
    defaults.update(overrides)
    return defaults


def create_restock_run_payload(site_id: str, driver_id: str, planned_date: str,
                               expected_site_version: int, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "driver_id": driver_id,
        "planned_date": planned_date,
        "expected_site_version": expected_site_version,
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(site_id: str, period_start: str, period_end: str,
                                        **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_session_payload(site_id: str, business_date: str, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "business_date": business_date,
    }
    defaults.update(overrides)
    return defaults
