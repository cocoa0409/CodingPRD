"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _next(tag: str) -> str:
    _counter["n"] += 1
    return f"{tag}-{_counter['n']}"


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": _next("Tech"),
        "capability": "TECHNICIAN",
        "base_hourly_rate_cents": TEST_DEFAULTS["TECH_RATE_CENTS"],
        "on_call_differential_bp": TEST_DEFAULTS["ON_CALL_DIFFERENTIAL_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_supervisor_payload(**overrides) -> dict:
    defaults = {
        "full_name": _next("Sup"),
        "capability": "SUPERVISOR",
        "base_hourly_rate_cents": TEST_DEFAULTS["SUPERVISOR_RATE_CENTS"],
        "on_call_differential_bp": TEST_DEFAULTS["ON_CALL_DIFFERENTIAL_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_number": _next("U"),
        "building_code": "B1",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": _next("Vendor"),
        "trade": "GENERAL",
        "per_incident_limit_cents": TEST_DEFAULTS["VENDOR_PER_INCIDENT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rotation_shift_payload(**overrides) -> dict:
    defaults = {
        "technician_id": None,
        "start_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_call_ticket_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "caller_name": "Resident Caller",
        "caller_phone": "555-0100",
        "category": "LEAK_MINOR",
        "description": "Problem reported by resident",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "call_ticket_id": None,
        "title": _next("WO"),
        "description": "Standard repair work",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_authorization_payload(**overrides) -> dict:
    defaults = {
        "work_order_id": None,
        "vendor_id": None,
        "amount_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_relocation_case_payload(**overrides) -> dict:
    defaults = {
        "unit_id": None,
        "call_ticket_id": None,
        "start_date": "2026-08-03T00:00:00Z",
        "end_date": "2026-08-05T00:00:00Z",
        "nightly_rate_cents": TEST_DEFAULTS["NIGHTLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_record_payload(**overrides) -> dict:
    defaults = {
        "narrative": "Chronological account of the incident response.",
        "estimated_damage_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_pay_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(lines=None, **overrides) -> dict:
    defaults = {
        "lines": lines
        or [{"description": "job", "quantity": 1, "unit_cost_cents": 10000}],
        "overhead_markup_bp": 1000,
    }
    defaults.update(overrides)
    return defaults
