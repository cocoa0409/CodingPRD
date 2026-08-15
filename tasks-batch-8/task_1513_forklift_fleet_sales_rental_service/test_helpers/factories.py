"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_serial_counter = itertools.count(1)


def next_serial(prefix="SN"):
    """Unique serial numbers so the cross-test unique constraint never trips."""
    return f"{prefix}-{next(_serial_counter):05d}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "credit_limit_cents": TEST_DEFAULTS["CUSTOMER_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "serial_number": next_serial(),
        "model": "8FGCU25",
        "power_type": "LP",
        "disposition": "RENTAL_FLEET",
        "daily_rate_cents": TEST_DEFAULTS["DAILY_RATE_CENTS"],
        "weekly_rate_cents": TEST_DEFAULTS["WEEKLY_RATE_CENTS"],
        "monthly_rate_cents": TEST_DEFAULTS["MONTHLY_RATE_CENTS"],
        "pm_interval_hours": TEST_DEFAULTS["PM_INTERVAL_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "kind": "NEW_CONFIG",
        "valid_until": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults


def create_quote_line_payload(**overrides) -> dict:
    defaults = {
        "description": "Attachment line",
        "qty": 1,
        "unit_price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_rental_contract_payload(unit_id, customer_id, expected_unit_version,
                                   **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "start_date": "2026-08-01",
        "end_date": "2026-08-03",
        "expected_unit_version": expected_unit_version,
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(**overrides) -> dict:
    defaults = {"reading_hours": 10}
    defaults.update(overrides)
    return defaults


def create_fuel_event_payload(**overrides) -> dict:
    defaults = {"event_type": "LP_REFILL", "cylinders": 1}
    defaults.update(overrides)
    return defaults


def create_service_call_payload(unit_id, customer_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "call_type": "BREAKDOWN",
        "priority": "STANDARD",
        "required_parts": [],
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(technician_id, **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "scheduled_start": "2026-08-02T10:00:00Z",
        "scheduled_end": "2026-08-02T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Tech",
        "home_branch": "BR1",
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "full_name": "Test Operator",
        "badge_number": "B-1",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "cert_class": "SIT_DOWN",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_lease_contract_payload(unit_id, customer_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "start_date": "2025-08-01",
        "end_date": "2026-08-01",
        "allowed_hours": 1000,
        "excess_hour_rate_cents": 500,
        "residual_value_cents": 800000,
    }
    defaults.update(overrides)
    return defaults


def create_lease_inspection_payload(**overrides) -> dict:
    defaults = {
        "condition_grade": "B",
        "hours_at_return": 1200,
        "appraised_value_cents": 530000,
    }
    defaults.update(overrides)
    return defaults


def create_reconditioning_order_payload(unit_id, **overrides) -> dict:
    defaults = {"unit_id": unit_id}
    defaults.update(overrides)
    return defaults
