"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional seconds."""
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 instants denote the same point in time."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict):
    """Primary-resource system properties (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict):
    """Append-only events carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for field in (
        "n400_fee_cents", "biometric_fee_cents", "translation_stipend_cents",
        "poverty_base_cents", "poverty_per_additional_cents",
        "full_waiver_threshold_pct", "partial_waiver_threshold_pct",
        "attendance_complete_bp", "attendance_midterm_floor_bp",
        "readiness_certify_threshold", "rfe_deadline_days",
        "accreditation_valid_months", "general_training_hours",
        "legal_supervised_hours", "renewal_training_hours",
        "promotion_offer_hours", "mock_buffer_minutes", "mock_max_attempts",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_applicant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["preferred_language"], str) and data["preferred_language"]
    assert data["stage"] in (
        "REGISTERED", "SCREENED", "IN_PIPELINE", "FILED", "NATURALIZED"
    )
    assert data.get("current_screening_id") is None or is_valid_uuid(data["current_screening_id"])
    assert isinstance(data["voter_registration_referred"], bool)


def assert_screening(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["marital_to_citizen"], bool)
    assert isinstance(data["lpr_months"], int)
    assert isinstance(data["continuous_residence_months"], int)
    assert isinstance(data["physical_presence_days"], int)
    assert isinstance(data["age_years"], int)
    assert isinstance(data["english_level"], int) and 0 <= data["english_level"] <= 4
    assert isinstance(data["civics_practice_pct"], int) and 0 <= data["civics_practice_pct"] <= 100
    assert isinstance(data["has_legal_flag"], bool)
    assert data["outcome"] in (
        "ELIGIBLE", "ELIGIBLE_WITH_EXEMPTION", "NOT_ELIGIBLE", "NEEDS_REVIEW"
    )
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601 UTC"


def assert_class_section(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["end_minute"] > data["start_minute"]
    assert isinstance(data["room_id"], str) and data["room_id"]
    assert is_valid_uuid(data["instructor_volunteer_id"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["total_sessions"], int) and data["total_sessions"] >= 2
    assert_seat_ledger_invariants(data)


def assert_seat_ledger_invariants(section: dict):
    """Pinned seat-ledger accounting (PRD §3.4): counters non-negative and
    seats_open == capacity - enrolled_count - pending_promotion_count."""
    enrolled = section["enrolled_count"]
    pending = section["pending_promotion_count"]
    waitlisted = section["waitlisted_count"]
    for name, value in (("enrolled_count", enrolled), ("pending_promotion_count", pending),
                        ("waitlisted_count", waitlisted)):
        assert isinstance(value, int) and value >= 0, f"{name} must be a non-negative integer"
    assert section["seats_open"] == section["capacity"] - enrolled - pending, (
        f"seats_open {section['seats_open']} != capacity {section['capacity']} "
        f"- enrolled_count {enrolled} - pending_promotion_count {pending}"
    )


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["class_section_id"])
    assert data["status"] in (
        "ENROLLED", "WAITLISTED", "PENDING_PROMOTION", "COMPLETED", "WITHDRAWN", "REVOKED"
    )
    assert isinstance(data["attendance_bp"], int) and 0 <= data["attendance_bp"] <= 10000
    assert isinstance(data["records_count"], int) and data["records_count"] >= 0
    assert data.get("offer_expires_at") is None or is_iso8601_timestamp(data["offer_expires_at"])


def assert_attendance_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["session_index"], int) and data["session_index"] >= 1
    assert data["outcome"] in ("PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["background_check_cleared"], bool)
    assert data.get("bar_number") is None or isinstance(data["bar_number"], str)
    assert data["accreditation_level"] in ("TRAINEE", "GENERAL", "LEGAL", "LAPSED")
    assert data.get("lapsed_from_level") in (None, "GENERAL", "LEGAL")
    assert data.get("accredited_at") is None or is_iso8601_timestamp(data["accredited_at"])
    assert isinstance(data["training_hours_24mo"], int) and data["training_hours_24mo"] >= 0
    assert isinstance(data["supervised_hours"], int) and data["supervised_hours"] >= 0


def assert_training_credit(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["volunteer_id"])
    assert isinstance(data["topic"], str) and data["topic"]
    assert isinstance(data["hours"], int) and data["hours"] >= 1
    assert is_iso8601_timestamp(data.get("earned_at", "")), "earned_at must be ISO 8601 UTC"


def assert_workshop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert is_valid_uuid(data["supervising_volunteer_id"])
    assert data.get("assisting_volunteer_id") is None or is_valid_uuid(data["assisting_volunteer_id"])
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "scheduled_start must be ISO 8601"
    assert isinstance(data["duration_hours"], int) and data["duration_hours"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and 0 <= data["reserved_count"] <= data["capacity"]
    assert data["status"] in ("SCHEDULED", "COMPLETED", "COMPLETION_REVERSED", "CANCELLED")


def assert_workshop_seat(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["workshop_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert data["status"] in ("RESERVED", "ATTENDED", "REVERSED", "CANCELLED")


def assert_packet(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["workshop_seat_id"])
    assert is_valid_uuid(data["prepared_by_volunteer_id"])
    assert data.get("fee_waiver_request_id") is None or is_valid_uuid(data["fee_waiver_request_id"])
    assert data["status"] in ("DRAFT", "IN_LEGAL_REVIEW", "NEEDS_REVISION", "CERTIFIED", "FILED")
    assert data.get("certified_by_volunteer_id") is None or is_valid_uuid(data["certified_by_volunteer_id"])
    assert data.get("filing_fee_cents") is None or (
        isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0
    )


def assert_fee_waiver_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["household_size"], int) and 1 <= data["household_size"] <= 12
    assert isinstance(data["self_reported_income_cents"], int) and data["self_reported_income_cents"] >= 0
    assert isinstance(data["self_reported_benefit"], bool)
    assert data["provisional_tier"] in ("FULL", "PARTIAL", "DENIED")
    assert isinstance(data["attached_document_count"], int) and data["attached_document_count"] >= 0
    assert isinstance(data["required_document_count"], int) and data["required_document_count"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED")
    assert data.get("documented_income_cents") is None or isinstance(data["documented_income_cents"], int)
    assert data.get("documented_benefit") is None or isinstance(data["documented_benefit"], bool)
    assert data.get("final_tier") in (None, "FULL", "PARTIAL")
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)


def assert_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["packet_id"])
    assert isinstance(data["receipt_number"], str) and data["receipt_number"].startswith("NRC-")
    assert data["stage"] in (
        "FILED", "RECEIPTED", "BIOMETRICS_COMPLETE", "INTERVIEW_SCHEDULED",
        "INTERVIEW_PASSED", "APPROVED_PENDING_OATH", "OATH_SCHEDULED",
        "NATURALIZED", "APPLICATION_DENIED",
    )
    assert data["rfe_status"] in ("NONE", "ISSUED", "RESPONDED", "OVERDUE")
    assert data.get("rfe_issued_at") is None or is_iso8601_timestamp(data["rfe_issued_at"])
    assert data.get("rfe_deadline") is None or is_iso8601_timestamp(data["rfe_deadline"])
    assert data.get("oath_ceremony_id") is None or is_valid_uuid(data["oath_ceremony_id"])


def assert_mock_interview(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["applicant_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), "scheduled_start must be ISO 8601"
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 10
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    for pct_field in ("english_pct", "civics_pct", "n400_pct"):
        assert data.get(pct_field) is None or (
            isinstance(data[pct_field], int) and 0 <= data[pct_field] <= 100
        )
    assert data.get("overall_score") is None or isinstance(data["overall_score"], int)
    assert data.get("outcome") in (None, "PASS", "NEEDS_RETRY")


def assert_oath_ceremony(data: dict):
    _assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("ceremony_date", "")), "ceremony_date must be ISO 8601"
    assert isinstance(data["venue"], str) and data["venue"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["assigned_count"], int) and 0 <= data["assigned_count"] <= data["capacity"]
    assert data["status"] in ("SCHEDULED", "CONCLUDED", "CANCELLED")


def assert_readiness_report(data: dict):
    assert data["variant"] in ("attained", "projected")
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    for field in ("residence_points", "presence_points", "english_points",
                  "civics_points", "legal_points"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
