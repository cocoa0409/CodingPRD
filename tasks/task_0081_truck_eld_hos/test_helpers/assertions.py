"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_DUTY_STATUSES = {"OFF_DUTY", "SLEEPER_BERTH", "DRIVING", "ON_DUTY_NOT_DRIVING"}
_SPECIAL_CATS = {"NONE", "PERSONAL_CONVEYANCE", "YARD_MOVE"}
_RECORD_STATUSES = {"ACTIVE", "INACTIVE_CHANGED", "INACTIVE_ERROR"}
_DISPOSITIONS = {"COMPLIANT", "VIOLATING"}
_VIOLATION_TYPES = {"DRIVING_11H", "WINDOW_14H", "CYCLE_70H", "BREAK_30MIN"}
_VIOLATION_STATUSES = {"OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"}
_CERT_STATUSES = {"UNCERTIFIED", "CERTIFIED", "RECERTIFY_REQUIRED"}
_CLAIM_STATUSES = {"PENDING", "APPROVED", "REJECTED"}


def _assert_common(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_driver(data: dict):
    _assert_common(data)
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_terminal_tz_offset_minutes"], int)
    assert -720 <= data["home_terminal_tz_offset_minutes"] <= 840
    assert data["cycle_rule"] in {"SEVENTY_HOUR_8_DAY", "SIXTY_HOUR_7_DAY"}
    assert data["status"] in {"ACTIVE", "DEACTIVATED"}
    assert isinstance(data["pc_authorized"], bool)
    assert data["current_duty_status"] in _DUTY_STATUSES
    assert isinstance(data["cycle_on_duty_minutes"], int) and data["cycle_on_duty_minutes"] >= 0


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["vin"], str)
    assert data["status"] in {"IN_SERVICE", "OUT_OF_SERVICE"}


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert is_valid_uuid(data.get("vehicle_id", "")), "vehicle_id must be a valid UUID"
    assert data["status"] in {"UNBOUND", "BOUND", "MALFUNCTION"}
    if data.get("bound_driver_id") is not None:
        assert is_valid_uuid(data["bound_driver_id"]), "bound_driver_id must be a UUID or null"


def assert_duty_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert is_valid_uuid(data.get("device_id", "")), "device_id must be a valid UUID"
    assert data["duty_status"] in _DUTY_STATUSES
    assert data["special_driving_category"] in _SPECIAL_CATS
    assert is_iso8601_timestamp(data.get("event_time", "")), "event_time must be ISO 8601"
    assert data["duration_minutes"] is None or (
        isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 0
    )
    assert data["record_status"] in _RECORD_STATUSES
    assert data["compliance_disposition"] in _DISPOSITIONS


def assert_daily_log(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert isinstance(data["log_date"], str)
    assert isinstance(data["total_driving_minutes"], int) and data["total_driving_minutes"] >= 0
    assert isinstance(data["total_on_duty_minutes"], int) and data["total_on_duty_minutes"] >= 0
    assert isinstance(data["total_off_duty_minutes"], int) and data["total_off_duty_minutes"] >= 0
    assert data["certification_status"] in _CERT_STATUSES
    if data["certification_status"] == "CERTIFIED":
        assert data.get("certified_at") is not None, "CERTIFIED log must carry certified_at"


def assert_violation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert is_valid_uuid(data.get("trigger_event_id", "")), "trigger_event_id must be a valid UUID"
    assert data["violation_type"] in _VIOLATION_TYPES
    assert isinstance(data["overage_minutes"], int) and data["overage_minutes"] >= 1
    assert data["status"] in _VIOLATION_STATUSES


def assert_adverse_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert isinstance(data["log_date"], str)
    assert data["reason"] in {"WEATHER", "ROAD_CLOSURE", "TRAFFIC_INCIDENT"}
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert data["status"] in _CLAIM_STATUSES


def assert_pc_segment(data: dict):
    """PC segment is append-only (PRD §2.4): id + created_at only, NO version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("driver_id", "")), "driver_id must be a valid UUID"
    assert is_valid_uuid(data.get("event_id", "")), "event_id must be a valid UUID"
    assert isinstance(data["minutes_excluded"], int) and data["minutes_excluded"] >= 0


def assert_no_version_field(data: dict):
    """PersonalConveyanceSegment carries neither version nor updated_at (PRD §2.4)."""
    assert "version" not in data, "PersonalConveyanceSegment must not expose a version field"
    assert "updated_at" not in data, "PersonalConveyanceSegment must not expose an updated_at field"
