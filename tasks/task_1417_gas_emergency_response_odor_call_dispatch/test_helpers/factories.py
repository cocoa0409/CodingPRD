"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import T1_THRESHOLDS

DEFAULTS = {
    "TERRITORY_NAME": "T1",
    "TECH_FULL_NAME": "Tech One",
    "TECH_BADGE": "B001",
    "HOURLY_RATE_CENTS": 6000,
    "CREW_CODE": "C1",
    "CALLER_NAME": "Caller",
    "CALLER_PHONE": "555-0100",
    "ADDRESS_LINE": "1 Main St",
    "CITY": "Springfield",
    "LOCATION_CONTEXT": "INSIDE_STRUCTURE",
    "PERIOD_START": "2026-08-01T00:00:00Z",
    "PERIOD_END": "2026-08-02T00:00:00Z",
}


def create_territory_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["TERRITORY_NAME"], **T1_THRESHOLDS}
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["TECH_FULL_NAME"],
        "badge_number": DEFAULTS["TECH_BADGE"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "shift_start": "2026-08-01T00:00:00Z",
        "shift_end": "2026-08-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "crew_code": DEFAULTS["CREW_CODE"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_emergency_call_payload(**overrides) -> dict:
    defaults = {
        "caller_name": DEFAULTS["CALLER_NAME"],
        "caller_phone": DEFAULTS["CALLER_PHONE"],
        "address_line": DEFAULTS["ADDRESS_LINE"],
        "city": DEFAULTS["CITY"],
        "location_context": DEFAULTS["LOCATION_CONTEXT"],
        "odor_reported": True,
        "symptoms_reported": False,
        "hissing_reported": False,
    }
    defaults.update(overrides)
    return defaults


def create_triage_payload(**overrides) -> dict:
    defaults = {"priority": "P2"}
    defaults.update(overrides)
    return defaults


def create_reclassify_payload(**overrides) -> dict:
    defaults = {"new_priority": "P1", "reason": "reclassify"}
    defaults.update(overrides)
    return defaults


def create_pause_payload(**overrides) -> dict:
    defaults = {"reason": "CUSTOMER_NOT_HOME"}
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    defaults = {"pct_lel": 1.0, "co_ppm": 0, "reading_context": "INSIDE"}
    defaults.update(overrides)
    return defaults


def create_make_safe_action_payload(**overrides) -> dict:
    defaults = {"action_type": "VENTILATE"}
    defaults.update(overrides)
    return defaults


def create_make_safe_complete_payload(**overrides) -> dict:
    defaults = {"leak_confirmed": False, "no_make_safe_required": True}
    defaults.update(overrides)
    return defaults


def create_entry_authorization_payload(**overrides) -> dict:
    defaults = {"method": "CUSTOMER_CONSENT", "authorized_by_name": "Occupant"}
    defaults.update(overrides)
    return defaults


def create_shutoff_order_payload(**overrides) -> dict:
    defaults = {"scope": "METER", "entry_required": False, "reason": "leak"}
    defaults.update(overrides)
    return defaults


def create_determination_payload(**overrides) -> dict:
    defaults = {"responsibility": "OUTSIDE_COMPANY", "basis": "BARHOLE_SURVEY"}
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-08-01T08:00:00Z",
        "window_end": "2026-08-01T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_notification_payload(**overrides) -> dict:
    defaults = {
        "channel": "MEDIA",
        "headline": "Gas odor reported",
        "body": "Crews responding",
    }
    defaults.update(overrides)
    return defaults
