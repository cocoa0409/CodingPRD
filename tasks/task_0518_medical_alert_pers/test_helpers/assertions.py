"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp) internally.
Field names are PRD-exact. DeviceTest is append-only and carries only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "PREMIUM")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["fall_detection_addon_cents"], int) and data["fall_detection_addon_cents"] >= 0
    assert isinstance(data["included_test_interval_days"], int) and data["included_test_interval_days"] >= 1
    assert isinstance(data["response_sla_seconds"], int) and data["response_sla_seconds"] >= 1
    assert isinstance(data["early_termination_fee_cents"], int) and data["early_termination_fee_cents"] >= 0
    assert isinstance(data["min_commitment_months"], int) and data["min_commitment_months"] >= 0
    assert isinstance(data["archived"], bool)


def assert_subscriber(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["residence_address"], str)
    assert isinstance(data["phone"], str)
    assert data["status"] == "ACTIVE"


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["service_status"] in (
        "PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "CANCELLATION_REQUESTED", "CANCELLED"
    )
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "WRITTEN_OFF")


def assert_device(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["device_type"] in ("PENDANT", "WRISTBAND", "MOBILE_GPS", "HOME_BASE")
    assert isinstance(data["fall_detection_enabled"], bool)
    assert data["status"] in (
        "REGISTERED", "ENROLLED", "ACTIVE", "NEEDS_TEST", "SUSPENDED", "DEACTIVATED"
    )
    assert isinstance(data["battery_pct"], int) and 0 <= data["battery_pct"] <= 100
    assert data["battery_health"] in ("GOOD", "LOW", "CRITICAL")
    assert isinstance(data["open_alarm_count"], int) and data["open_alarm_count"] >= 0


def assert_emergency_contact(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["subscriber_id"])
    assert isinstance(data["name"], str)
    assert data["relationship"] in ("CAREGIVER", "FAMILY", "NEIGHBOR", "PHYSICIAN")
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["can_authorize_911"], bool)
    assert isinstance(data["active"], bool)


def assert_alarm(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["signal_type"] in (
        "MANUAL_BUTTON", "FALL_DETECTED", "BATTERY_CRITICAL", "PERIODIC_CHECKIN_MISSED"
    )
    assert data["priority"] in ("ROUTINE", "ELEVATED", "CRITICAL")
    assert data["status"] in (
        "SIGNAL_RECEIVED", "AGENT_ASSIGNED", "CONTACTING_SUBSCRIBER", "ESCALATING",
        "DISPATCHED_911", "RESOLVED_OK", "FALSE_ALARM",
    )
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["current_escalation_rank"], int)
    assert isinstance(data["dispatch_count"], int) and data["dispatch_count"] >= 0


def assert_dispatch_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["alarm_event_id"])
    assert data["action_type"] in (
        "CALL_SUBSCRIBER", "CALL_CONTACT", "DISPATCH_911", "MARK_FALSE_ALARM", "RESOLVE_OK"
    )
    assert data["outcome"] in (
        "ANSWERED", "NO_ANSWER", "DISPATCHED", "CONFIRMED_OK", "CONFIRMED_FALSE"
    )


def assert_device_test(data: dict):
    """DeviceTest is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["device_id"])
    assert isinstance(data["reported_battery_pct"], int) and 0 <= data["reported_battery_pct"] <= 100
    assert isinstance(data["signal_ok"], bool)
    assert data["result"] in ("PASS", "FAIL_SIGNAL", "FAIL_BATTERY")


def assert_equipment_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["status"] in (
        "INITIATED", "KIT_SENT", "RECEIVED", "INSPECTED_OK", "DAMAGED", "CLOSED"
    )
    assert isinstance(data["damage_fee_cents"], int) and data["damage_fee_cents"] >= 0


def assert_agent_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["agent_user_id"], str) and len(data["agent_user_id"]) > 0
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_monitoring_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert data["status"] in ("SCHEDULED", "CANCELLED")
