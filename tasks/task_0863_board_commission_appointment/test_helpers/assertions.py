"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerant of a trailing Z and optional
    fractional seconds, so equality compares the instant not the spelling."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso_equal(actual: str, expected: str) -> bool:
    """True iff two ISO 8601 strings denote the same UTC instant."""
    return _instant(actual) == _instant(expected)


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_board(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["board_type"] in ("BOARD", "COMMISSION", "AUTHORITY")
    assert data["status"] == "ACTIVE"
    assert isinstance(data["authorized_seat_count"], int)
    assert isinstance(data["quorum_count"], int)
    assert isinstance(data["max_holdover_days"], int)


def assert_seat(data: dict):
    _common(data)
    assert data["seat_category"] in ("AT_LARGE", "DISTRICT", "EX_OFFICIO")
    assert data["residency_requirement"] in ("IN_JURISDICTION", "DISTRICT_SPECIFIC", "NONE")
    assert data["occupancy_status"] in ("VACANT", "FILLED", "HOLDOVER")


def assert_vacancy(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CLOSED", "FILLED")
    assert data["reason"] in ("NEW_SEAT", "RESIGNATION", "TERM_EXPIRY", "REMOVAL")


def assert_applicant(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] == "ACTIVE"


def assert_application(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO",
                              "ELIGIBLE", "INELIGIBLE")
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0


def assert_appointment(data: dict):
    _common(data)
    assert data["status"] in ("NOMINATED", "CONFIRMED", "REJECTED", "SUPERSEDED")
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert isinstance(data["term_sequence_number"], int)


def assert_term(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "HOLDOVER", "EXPIRED", "VACATED", "COMPLETED")
    assert isinstance(data["present_count"], int)
    assert isinstance(data["absent_count"], int)
    assert isinstance(data["excused_count"], int)


def assert_meeting(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "NOTICED", "HELD")


def assert_attendance_record(data: dict):
    """AttendanceRecord carries ONLY id + created_at (immutable, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["presence"] in ("PRESENT", "ABSENT", "EXCUSED")
    assert "version" not in data, "AttendanceRecord is immutable — no version field"
    assert "updated_at" not in data, "AttendanceRecord is immutable — no updated_at field"


def assert_disclosure(data: dict):
    _common(data)
    assert data["filing_type"] in ("FINANCIAL_DISCLOSURE", "ETHICS_PLEDGE")
    assert data["status"] in ("PENDING", "FILED", "ACCEPTED", "DEFICIENT", "CLOSED")


def assert_removal(data: dict):
    _common(data)
    assert data["status"] in ("INITIATED", "EXECUTED")
    assert data["reason"] in ("RESIGNATION", "TERM_LIMIT", "ATTENDANCE",
                              "ETHICS_VIOLATION", "FOR_CAUSE")


def assert_reappointment(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")
