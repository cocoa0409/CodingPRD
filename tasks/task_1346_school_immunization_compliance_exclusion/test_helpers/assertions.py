"""Entity assertions and domain invariant checkers (PRD sections 2.5, 3.1-3.9)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AppointmentStatus,
    ExemptionStatus,
    ExemptionType,
    Grade,
    NoticeStatus,
    NoticeType,
    OutbreakStatus,
    RateVariant,
    RecordSource,
    RecordStatus,
    SessionStatus,
    SnapshotStatus,
    StudentStatus,
    SyncRunStatus,
    VaccineCode,
)

_GRADES = [g.value for g in Grade]
_VACCINE_CODES = [v.value for v in VaccineCode]
_STUDENT_STATUSES = [s.value for s in StudentStatus]
_RECORD_STATUSES = [s.value for s in RecordStatus]
_RECORD_SOURCES = [s.value for s in RecordSource]
_EXEMPTION_TYPES = [t.value for t in ExemptionType]
_EXEMPTION_STATUSES = [s.value for s in ExemptionStatus]
_NOTICE_TYPES = [t.value for t in NoticeType]
_NOTICE_STATUSES = [s.value for s in NoticeStatus]
_OUTBREAK_STATUSES = [s.value for s in OutbreakStatus]
_SESSION_STATUSES = [s.value for s in SessionStatus]
_APPOINTMENT_STATUSES = [s.value for s in AppointmentStatus]
_SYNC_RUN_STATUSES = [s.value for s in SyncRunStatus]
_SNAPSHOT_STATUSES = [s.value for s in SnapshotStatus]
_RATE_VARIANTS = [v.value for v in RateVariant]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant; comparisons are at second precision (PRD 2.4)."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instants_equal(actual, expected_iso: str, label: str = "instant"):
    """Assert two instants denote the same point in time, regardless of rendering."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """PRD 2.5 system-managed fields present on every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_optional_instant(value, field):
    assert value is None or isinstance(value, str), f"{field} must be null or a string"
    if value is not None:
        parse_instant(value)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    parse_instant(data["date_of_birth"])
    assert data["grade"] in _GRADES, f"grade must be a declared grade, got {data['grade']!r}"
    assert isinstance(data["school_code"], str) and data["school_code"]
    parse_instant(data["enrollment_date"])
    assert data["status"] in _STUDENT_STATUSES
    parse_instant(data["provisional_deadline"])
    assert isinstance(data["deficiency_vaccine_codes"], list)
    for code in data["deficiency_vaccine_codes"]:
        assert code in _VACCINE_CODES


def assert_vaccine_requirement(data: dict):
    _assert_common_fields(data)
    assert data["vaccine_code"] in _VACCINE_CODES
    assert isinstance(data["applies_to_grades"], list) and data["applies_to_grades"]
    for grade in data["applies_to_grades"]:
        assert grade in _GRADES
    assert isinstance(data["doses_required"], int) and data["doses_required"] >= 1
    assert isinstance(data["min_interval_days"], int) and data["min_interval_days"] >= 0
    assert isinstance(data["min_age_months"], int) and data["min_age_months"] >= 0
    assert isinstance(data["school_year"], str) and data["school_year"]


def assert_immunization_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["vaccine_code"] in _VACCINE_CODES
    assert isinstance(data["dose_number"], int) and data["dose_number"] >= 1
    parse_instant(data["administered_date"])
    assert data["source"] in _RECORD_SOURCES
    assert data["clinic_appointment_id"] is None or isinstance(
        data["clinic_appointment_id"], str
    )
    assert data["status"] in _RECORD_STATUSES
    assert data["verified_by_user_id"] is None or isinstance(
        data["verified_by_user_id"], str
    )


def assert_exemption_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["vaccine_code"] in _VACCINE_CODES
    assert data["exemption_type"] in _EXEMPTION_TYPES
    assert isinstance(data["document_ref"], str) and data["document_ref"]
    assert data["status"] in _EXEMPTION_STATUSES
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    assert data["reviewed_by_user_id"] is None or isinstance(
        data["reviewed_by_user_id"], str
    )
    assert data["denial_reason"] is None or isinstance(data["denial_reason"], str)


def assert_compliance_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["notice_type"] in _NOTICE_TYPES
    assert data["status"] in _NOTICE_STATUSES
    parse_instant(data["issue_date"])
    parse_instant(data["exclusion_date"])
    _assert_optional_instant(data.get("resolved_at"), "resolved_at")


def assert_outbreak_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert data["vaccine_code"] in _VACCINE_CODES
    assert data["status"] in _OUTBREAK_STATUSES
    parse_instant(data["declared_at"])
    _assert_optional_instant(data.get("lifted_at"), "lifted_at")


def assert_clinic_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_code"], str) and data["school_code"]
    parse_instant(data["session_date"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert data["booked_count"] <= data["capacity"]
    assert data["status"] in _SESSION_STATUSES


def assert_clinic_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["clinic_session_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["vaccine_code"] in _VACCINE_CODES
    assert parse_instant(data["start_time"]) < parse_instant(data["end_time"])
    assert data["status"] in _APPOINTMENT_STATUSES


def assert_registry_sync_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert data["status"] in _SYNC_RUN_STATUSES
    for counter in (
        "registry_doses_seen",
        "imported_count",
        "matched_count",
        "discrepancy_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_compliance_snapshot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["school_year"], str) and data["school_year"]
    assert isinstance(data["school_code"], str) and data["school_code"]
    assert data["grade"] in _GRADES
    parse_instant(data["census_date"])
    assert data["rate_variant"] in _RATE_VARIANTS
    for counter in ("enrolled_count", "compliant_count", "exempt_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert data["compliance_rate"] is None or isinstance(
        data["compliance_rate"], (int, float)
    )
    assert data["status"] in _SNAPSHOT_STATUSES
