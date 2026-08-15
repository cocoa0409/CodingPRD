"""Entity assertions and domain invariant checkers (field names per PRD)."""
from datetime import datetime, timezone
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC datetime string, tolerating 'Z' or offsets."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(actual: str, expected_iso: str) -> bool:
    """True when two ISO 8601 strings denote the same instant (to the second)."""
    return _parse_instant(actual) == _parse_instant(expected_iso)


def assert_instant(actual: str, expected_iso: str, label: str = "instant"):
    assert isinstance(actual, str), f"{label} must be a string, got {type(actual)}"
    assert instants_equal(actual, expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def _assert_common(data: Dict[str, Any]):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def _assert_append_only(data: Dict[str, Any]):
    """StudentTeacherLink and AttendanceRecord carry only id + created_at (PRD 2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must not carry updated_at"
    assert "version" not in data, "append-only resource must not carry version"


def assert_window(data: Dict[str, Any]):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["term_label"], str) and data["term_label"]
    assert data["format"] in ("ELEMENTARY", "SECONDARY")
    assert isinstance(data["slot_length_minutes"], int) and data["slot_length_minutes"] > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["travel_minutes"], int) and data["travel_minutes"] >= 0
    assert isinstance(data["day_windows"], list)
    assert data["status"] in (
        "DRAFT", "PUBLISHED", "BOOKING_OPEN", "LOCKED",
        "IN_PROGRESS", "COMPLETED", "ARCHIVED",
    )
    for counter in (
        "ops_run_index",
        "slots_total_count",
        "slots_open_count",
        "slots_held_count",
        "slots_booked_count",
        "bookings_confirmed_count",
        "waitlist_waiting_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )


def assert_teacher(data: Dict[str, Any]):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["grade_band"] in ("ELEMENTARY", "SECONDARY", "BOTH")
    assert isinstance(data["subjects"], list)
    assert isinstance(data["supports_in_person"], bool)
    assert isinstance(data["supports_virtual"], bool)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_family(data: Dict[str, Any]):
    _assert_common(data)
    assert isinstance(data["primary_guardian_name"], str) and data["primary_guardian_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ACTIVE", "RESTRICTED")
    assert isinstance(data["no_show_strike_count"], int) and data["no_show_strike_count"] >= 0
    assert isinstance(data["strikes_cleared_total"], int) and data["strikes_cleared_total"] >= 0
    assert isinstance(data["attendance_risk_strict"], (int, float))
    assert isinstance(data["attendance_risk_score"], (int, float))


def assert_student(data: Dict[str, Any]):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12
    assert data["enrollment_status"] in ("ENROLLED", "WITHDRAWN")
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"


def assert_student_teacher_link(data: Dict[str, Any]):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("teacher_id", "")), "teacher_id must be a UUID"
    assert isinstance(data["is_homeroom"], bool)
    assert isinstance(data["required_conference"], bool)


def assert_time_slot(data: Dict[str, Any]):
    _assert_common(data)
    assert is_valid_uuid(data.get("window_id", "")), "window_id must be a UUID"
    assert is_valid_uuid(data.get("teacher_id", "")), "teacher_id must be a UUID"
    assert isinstance(data["day_label"], str) and data["day_label"]
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert data["channel_allowed"] in ("IN_PERSON", "VIRTUAL", "EITHER")
    assert data["status"] in ("OPEN", "BLOCKED", "HELD", "BOOKED", "RETIRED")


def assert_booking(data: Dict[str, Any]):
    _assert_common(data)
    for fk in ("window_id", "family_id", "student_id", "teacher_id", "slot_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["channel"] in ("IN_PERSON", "VIRTUAL")
    assert data["booked_by_role"] in ("FAMILY_SELF", "FRONT_OFFICE")
    assert data["status"] in (
        "CONFIRMED", "COMPLETED", "NO_SHOW", "EXCUSED", "CANCELLED", "RESCHEDULED",
    )
    assert isinstance(data["family_compactness_score"], (int, float))


def assert_interpreter(data: Dict[str, Any]):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["languages"], list) and len(data["languages"]) > 0
    assert isinstance(data["supports_in_person"], bool)
    assert isinstance(data["supports_virtual"], bool)
    assert isinstance(data["max_consecutive_minutes"], int) and data["max_consecutive_minutes"] > 0
    assert isinstance(data["base_minutes_per_window"], int) and data["base_minutes_per_window"] > 0
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_interpreter_request(data: Dict[str, Any]):
    _assert_common(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert is_valid_uuid(data.get("window_id", "")), "window_id must be a UUID"
    assert isinstance(data["language"], str) and data["language"]
    assert data["channel_required"] in ("IN_PERSON", "VIRTUAL")
    assert isinstance(data["assigned_minutes"], int) and data["assigned_minutes"] > 0
    assert isinstance(data["declined_interpreter_ids"], list)
    assert data["status"] in ("REQUESTED", "ASSIGNED", "CONFIRMED", "CANCELLED", "UNFILLED")


def assert_waitlist_entry(data: Dict[str, Any]):
    _assert_common(data)
    for fk in ("window_id", "family_id", "student_id", "teacher_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["channel_pref"] in ("IN_PERSON", "VIRTUAL", "EITHER")
    assert data["status"] in (
        "WAITING", "OFFERED", "CLAIMED", "EXPIRED", "WITHDRAWN", "EXHAUSTED",
    )
    assert isinstance(data["offers_made_count"], int) and data["offers_made_count"] >= 0
    assert isinstance(data["declined_slot_ids"], list)
    assert isinstance(data["priority_score"], (int, float))


def assert_attendance_record(data: Dict[str, Any]):
    _assert_append_only(data)
    assert is_valid_uuid(data.get("booking_id", "")), "booking_id must be a UUID"
    assert data["outcome"] in ("ATTENDED", "LATE", "NO_SHOW", "EXCUSED")
    assert isinstance(data["marked_by_role"], str) and data["marked_by_role"]
    assert isinstance(data["marked_by_user_id"], str) and data["marked_by_user_id"]


def assert_outreach_task(data: Dict[str, Any]):
    _assert_common(data)
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"
    assert data["kind"] in ("NO_SHOW_FOLLOW_UP", "RESCHEDULE_ASSIST", "LANGUAGE_ACCESS")
    assert data["status"] in ("OPEN", "CONTACTED", "RESOLVED", "DISMISSED")
    assert isinstance(data["attempts_count"], int) and data["attempts_count"] >= 0


def assert_window_counters(data: Dict[str, Any], *, total=None, open_=None, held=None,
                           booked=None, confirmed=None, waiting=None):
    """Window live-counter invariant check (PRD 2.8)."""
    if total is not None:
        assert data["slots_total_count"] == total, (
            f"slots_total_count: expected {total}, got {data['slots_total_count']}"
        )
    if open_ is not None:
        assert data["slots_open_count"] == open_, (
            f"slots_open_count: expected {open_}, got {data['slots_open_count']}"
        )
    if held is not None:
        assert data["slots_held_count"] == held, (
            f"slots_held_count: expected {held}, got {data['slots_held_count']}"
        )
    if booked is not None:
        assert data["slots_booked_count"] == booked, (
            f"slots_booked_count: expected {booked}, got {data['slots_booked_count']}"
        )
    if confirmed is not None:
        assert data["bookings_confirmed_count"] == confirmed, (
            f"bookings_confirmed_count: expected {confirmed}, got {data['bookings_confirmed_count']}"
        )
    if waiting is not None:
        assert data["waitlist_waiting_count"] == waiting, (
            f"waitlist_waiting_count: expected {waiting}, got {data['waitlist_waiting_count']}"
        )
