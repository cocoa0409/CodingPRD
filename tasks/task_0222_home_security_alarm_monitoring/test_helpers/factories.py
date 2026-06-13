"""Payload factories — one per creatable entity, input fields only.

Each factory builds a valid default payload using only the fields the PRD
declares as client-supplied input, and accepts **overrides for the values a
test needs to control.
"""

DEFAULTS = {
    "PLAN_MONTHLY_FEE_CENTS": 1500,
    "PLAN_MAX_SENSORS": 8,
    "CONTRACT_TERM_MONTHS": 12,
    "SIGNAL_DBM": -60,
    "BATTERY_PCT": 100,
    "CHECKIN_MIN_AGO": 5,
}


def create_monitoring_plan_payload(**overrides) -> dict:
    """Input fields for POST /monitoring-plans."""
    defaults = {
        "tier": "BASIC",
        "monthly_fee_cents": DEFAULTS["PLAN_MONTHLY_FEE_CENTS"],
        "police_dispatch_included": False,
        "max_sensors": DEFAULTS["PLAN_MAX_SENSORS"],
        "cellular_backup_included": False,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(plan_id: str, **overrides) -> dict:
    """Input fields for POST /accounts."""
    defaults = {
        "premises_type": "RESIDENTIAL",
        "plan_id": plan_id,
        "contract_term_months": DEFAULTS["CONTRACT_TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_system_payload(account_id: str, **overrides) -> dict:
    """Input fields for POST /systems."""
    defaults = {
        "account_id": account_id,
        "primary_path": "BROADBAND",
        "cellular_signal_dbm": DEFAULTS["SIGNAL_DBM"],
        "backup_battery_pct": DEFAULTS["BATTERY_PCT"],
        "last_checkin_minutes_ago": DEFAULTS["CHECKIN_MIN_AGO"],
    }
    defaults.update(overrides)
    return defaults


def create_sensor_payload(system_id: str, **overrides) -> dict:
    """Input fields for POST /sensors."""
    defaults = {
        "system_id": system_id,
        "zone_number": 1,
        "sensor_type": "DOOR",
    }
    defaults.update(overrides)
    return defaults


def create_alarm_event_payload(system_id: str, sensor_id: str, **overrides) -> dict:
    """Input fields for POST /alarm-events."""
    defaults = {
        "system_id": system_id,
        "sensor_id": sensor_id,
        "signal_type": "BURGLARY",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(account_id: str, permit_number: str, **overrides) -> dict:
    """Input fields for POST /permits."""
    defaults = {
        "account_id": account_id,
        "permit_number": permit_number,
        "filed_days_late": 0,
    }
    defaults.update(overrides)
    return defaults


def change_plan_payload(new_plan_id: str, expected_account_version: int, **overrides) -> dict:
    """Input fields for POST /accounts/{id}/change-plan."""
    defaults = {
        "new_plan_id": new_plan_id,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def finalize_cancellation_payload(expected_account_version: int, **overrides) -> dict:
    """Input fields for POST /accounts/{id}/finalize-cancellation."""
    defaults = {"expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def arm_payload(mode: str = "ARMED_AWAY", **overrides) -> dict:
    """Input fields for POST /systems/{id}/arm."""
    defaults = {"mode": mode}
    defaults.update(overrides)
    return defaults


def resolve_payload(resolution: str, **overrides) -> dict:
    """Input fields for POST /alarm-events/{id}/resolve."""
    defaults = {"resolution": resolution}
    defaults.update(overrides)
    return defaults
