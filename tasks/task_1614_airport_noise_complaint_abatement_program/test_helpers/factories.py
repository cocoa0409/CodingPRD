"""Payload factories — one per creatable resource, input fields only (PRD 4)."""
import itertools

from .constants import TEST_DEFAULTS

# Process-local uniquifiers for fields with uniqueness rules. The API
# database resets per test, but several resources of the same kind may be
# created inside one test, so generated tokens must never repeat.
_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def _iata() -> str:
    n = _next()
    return "X" + chr(ord("A") + (n // 26) % 26) + chr(ord("A") + n % 26)


def create_complainant_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Test Complainant {n}",
        "email": f"complainant{n}@example.com",
        "address_line": f"{n} Quiet Skies Way",
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(complainant_id: str, **overrides) -> dict:
    defaults = {
        "complainant_id": complainant_id,
        "occurred_at": "2026-07-15T09:00:00Z",
        "channel": "WEB",
        "disturbance_type": "OTHER",
    }
    defaults.update(overrides)
    return defaults


def create_operator_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Test Carrier {n}",
        "iata_code": _iata(),
        "contact_email": f"ops{n}@carrier.example",
    }
    defaults.update(overrides)
    return defaults


def create_flight_payload(operator_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "flight_number": f"TS{n}",
        "operator_id": operator_id,
        "aircraft_type": "B738",
        "engine_class": "STAGE_4",
        "operation_type": "DEPARTURE",
        "runway_code": TEST_DEFAULTS["RUNWAY_CODE"],
        "scheduled_at": "2026-07-15T11:55:00Z",
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_monitor_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "station_code": f"ST-{n:04d}",
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
        "latitude": 47.1,
        "longitude": -122.3,
        "commissioned_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_outage_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-07-10T10:00:00Z",
        "end_at": "2026-07-10T11:00:00Z",
        "outage_type": "MAINTENANCE",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "started_at": "2026-07-20T10:00:00Z",
        "duration_seconds": 40,
        "lmax_db": 72.0,
        "sel_db": 90.0,
    }
    defaults.update(overrides)
    return defaults


def create_curfew_rule_payload(**overrides) -> dict:
    defaults = {
        "runway_code": TEST_DEFAULTS["RUNWAY_CODE"],
        "season": "YEAR_ROUND",
        "window_start_minute": 1320,
        "window_end_minute": 1439,
        "applies_to": "DEPARTURE",
        "grace_minutes": 15,
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(operator_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "operator_id": operator_id,
        "severity": "FORMAL",
        "subject": f"Noise inquiry {n}",
        "body": "Please review this operation and respond.",
    }
    defaults.update(overrides)
    return defaults


def create_study_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "title": f"Part 150 Study {n}",
        "baseline_year": 2025,
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "parcel_ref": f"P-{n:04d}",
        "land_use": "RESIDENTIAL",
        "dnl_db_measured": 66.0,
        "dnl_db_modeled": 67.5,
        "zone_code": TEST_DEFAULTS["ZONE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "fiscal_year": f"FY{2100 + n}",
        "total_allocation_cents": TEST_DEFAULTS["FUND_TOTAL_CENTS"],
        "intake_opens_at": TEST_DEFAULTS["INTAKE_OPENS"],
        "intake_closes_at": TEST_DEFAULTS["INTAKE_CLOSES"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(parcel_id: str, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "dwelling_type": "SINGLE_FAMILY",
        "rooms_count": 4,
        "est_cost_cents": 500_000,
    }
    defaults.update(overrides)
    return defaults


def create_outreach_case_payload(complainant_id: str, **overrides) -> dict:
    defaults = {
        "complainant_id": complainant_id,
        "trigger_reason": "MANUAL",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "quarter_label": "2026-Q2",
    }
    defaults.update(overrides)
    return defaults
