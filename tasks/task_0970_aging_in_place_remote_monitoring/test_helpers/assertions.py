"""Entity assertions and domain invariant checkers (PRD 2.5, 2.6, 2.7)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resources must not carry updated_at"
    assert "version" not in data, "append-only resources must not carry version"


def assert_senior(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["address"], str)
    assert data["monitoring_posture"] in ["INACTIVE", "ACTIVE", "DEGRADED"]
    assert isinstance(data["open_alert_count"], int) and data["open_alert_count"] >= 0
    assert data["risk_tier"] in ["STANDARD", "ELEVATED"]


def assert_subscription_plan(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ["ESSENTIAL", "PLUS", "PREMIUM"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["included_motion_sensors"], int)
    assert isinstance(data["extra_sensor_fee_cents"], int)
    assert isinstance(data["max_contacts"], int)
    assert isinstance(data["checkin_interval_hours"], int)
    assert isinstance(data["medication_reminders_enabled"], bool)
    assert isinstance(data["wellness_report_enabled"], bool)
    assert data["wellness_report_cadence"] in ["NONE", "MONTHLY", "WEEKLY"]


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data["service_status"] in [
        "PROVISIONING",
        "ACTIVE",
        "SUSPENDED",
        "CANCELLED",
    ]
    assert data["billing_status"] in ["CURRENT", "PAST_DUE", "DELINQUENT"]
    assert isinstance(data["billing_credit_cents"], int)
    assert isinstance(data["lifetime_charged_cents"], int)
    assert isinstance(data["lifetime_credited_cents"], int)
    assert isinstance(data["consecutive_failed_payments"], int)


def assert_sensor_kit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert isinstance(data["motion_sensor_count"], int)
    assert data["status"] in [
        "ORDERED",
        "SHIPPED",
        "DELIVERED",
        "INSTALLED",
        "ACTIVE",
    ]


def assert_device(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("kit_id", ""))
    assert is_valid_uuid(data.get("senior_id", ""))
    assert data["device_type"] in ["GATEWAY", "WEARABLE", "MOTION"]
    assert isinstance(data["serial"], str) and len(data["serial"]) > 0
    assert data["status"] in [
        "PROVISIONED",
        "INSTALLED",
        "ONLINE",
        "OFFLINE",
        "DECOMMISSIONED",
    ]
    assert isinstance(data["battery_percent"], int)
    assert 0 <= data["battery_percent"] <= 100


def assert_sensor_event(data: dict):
    """Append-only resource: id + created_at only (PRD 2.5)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("device_id", ""))
    assert data["event_type"] in [
        "HEARTBEAT",
        "MOTION",
        "DOOR_OPEN",
        "DOOR_CLOSE",
        "FALL_DETECTED",
        "PILL_DISPENSED",
    ]
    assert is_iso8601_timestamp(data.get("observed_at", ""))


def assert_installer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["region"], str)


def assert_install_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert is_valid_uuid(data.get("kit_id", ""))
    assert is_valid_uuid(data.get("installer_id", ""))
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["status"] in [
        "SCHEDULED",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    ]


def assert_caregiver(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str)


def assert_contact_tree_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert is_valid_uuid(data.get("caregiver_id", ""))
    assert isinstance(data["priority_rank"], int)
    assert data["min_severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert isinstance(data["response_timeout_seconds"], int)
    assert data["status"] in ["ACTIVE", "REMOVED"]


def assert_alert(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert data["alert_type"] in [
        "FALL",
        "INACTIVITY",
        "MISSED_MEDICATION",
        "MISSED_CHECKIN",
        "DEVICE_OFFLINE",
        "LOW_BATTERY",
        "MANUAL",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in [
        "RAISED",
        "NOTIFYING",
        "ESCALATED",
        "ACKNOWLEDGED",
        "RESOLVED",
        "FALSE_ALARM",
    ]
    assert isinstance(data["escalation_level"], int)
    assert isinstance(data["escalation_exhausted"], bool)
    assert isinstance(data["reopen_count"], int)


def assert_alert_notification(data: dict):
    """Append-only resource: id + created_at only (PRD 2.5)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("alert_id", ""))
    assert isinstance(data["level"], int)
    assert data["status"] in ["SENT", "ACKED", "TIMED_OUT", "SUPERSEDED"]
    assert is_iso8601_timestamp(data.get("sent_at", ""))


def assert_medication_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert isinstance(data["medication_name"], str)
    assert isinstance(data["times_of_day"], list)
    assert isinstance(data["window_minutes"], int)
    assert data["criticality"] in ["ROUTINE", "CRITICAL"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["missed_streak"], int) and data["missed_streak"] >= 0
    assert data["status"] in ["ACTIVE", "ENDED"]


def assert_dose_event(data: dict):
    """Append-only resource: id + created_at only (PRD 2.5)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_valid_uuid(data.get("senior_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    assert data["status"] in ["PENDING", "TAKEN", "MISSED", "SKIPPED"]


def assert_check_in(data: dict):
    """Append-only resource: id + created_at only (PRD 2.5)."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert data["kind"] in ["SELF_CONFIRM", "APP_CONFIRM", "CALL", "VISIT"]
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


def assert_wellness_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("senior_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["mode"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["READY", "DELIVERED"]
    for field in (
        "activity_score",
        "adherence_pct",
        "device_health_pct",
        "wellness_index",
    ):
        value = data[field]
        assert 0.0 <= value <= 100.0, f"{field} must be within 0..100"
        # one decimal place exactly (PRD 2.7)
        assert abs(value * 10 - round(value * 10)) < 1e-6, (
            f"{field} must carry exactly one decimal place, got {value}"
        )
    assert isinstance(data["fall_cap_applied"], bool)
    assert isinstance(data["alert_count"], int)


def assert_senior_open_alert_invariant(senior: dict, alerts: list):
    """open_alert_count must equal the count of alerts in open statuses (PRD 2.6)."""
    open_statuses = {"RAISED", "NOTIFYING", "ESCALATED", "ACKNOWLEDGED"}
    actual = sum(1 for a in alerts if a.get("status") in open_statuses)
    assert senior["open_alert_count"] == actual, (
        f"open_alert_count {senior['open_alert_count']} != actual open alerts {actual}"
    )


def assert_subscription_net_position_invariant(subscription: dict):
    """lifetime counters and banked credit stay consistent (PRD 3.2)."""
    assert subscription["lifetime_charged_cents"] >= 0
    assert subscription["lifetime_credited_cents"] >= 0
    assert subscription["billing_credit_cents"] >= 0
