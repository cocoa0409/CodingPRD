"""Payload factories — one per creatable entity, input fields only (PRD 3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "code": f"PROG-{n}",
        "name": f"Program {n}",
        "sector": "RESIDENTIAL",
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "avoided_kwh_target": TEST_DEFAULTS["KWH_TARGET"],
        "trc_threshold": TEST_DEFAULTS["TRC_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "legal_name": f"Contractor {n} LLC",
        "license_number": f"LIC-{n}",
        "sector": "RESIDENTIAL",
        "service_zip_codes": [TEST_DEFAULTS["ZIP"]],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(contractor_id, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "measure_type": "HVAC",
        "issued_on": TEST_DEFAULTS["CERT_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["CERT_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Customer {n}",
        "email": f"customer{n}@example.com",
        "service_zip": TEST_DEFAULTS["ZIP"],
        "sector": "RESIDENTIAL",
        "utility_account_id": f"UA-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_lead_payload(customer_id, program_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "program_id": program_id,
        "measure_type": "HVAC",
        "estimated_annual_kwh_savings": 1000,
        "source_channel": "WEB",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(lead_id, customer_id, contractor_id, program_id, **overrides) -> dict:
    defaults = {
        "lead_id": lead_id,
        "customer_id": customer_id,
        "contractor_id": contractor_id,
        "program_id": program_id,
        "measure_type": "HVAC",
        "measure_cost_cents": 100000,
        "estimated_annual_kwh_savings": 1000,
        "incentive_recipient": "CONTRACTOR",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(contractor_id, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "scheduled_on": TEST_DEFAULTS["INSTALL_DATE"],
        "duration_hours": 4,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Inspector {n}",
        "license_number": f"INSP-{n}",
        "excluded_contractor_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(work_order_id, project_id, inspector_id, **overrides) -> dict:
    defaults = {
        "work_order_id": work_order_id,
        "project_id": project_id,
        "inspector_id": inspector_id,
        "scheduled_on": TEST_DEFAULTS["INSPECTION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def record_inspection_payload(**overrides) -> dict:
    defaults = {
        "outcome": "PASS",
        "score_bps": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(customer_id, contractor_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "contractor_id": contractor_id,
        "category": "WORKMANSHIP",
        "severity": "MEDIUM",
        "description": "Test complaint",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "total_admin_cost_cents": 50000,
    }
    defaults.update(overrides)
    return defaults
