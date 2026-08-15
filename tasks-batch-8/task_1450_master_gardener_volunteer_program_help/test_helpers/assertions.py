"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (is_iso8601_timestamp, is_valid_uuid)

from .types import (ActivityType, ApplicationStatus, CreditEntryStatus,
                    EnrollmentStatus, EntryKind, InquiryCategory,
                    InquiryResolution, InquiryStatus, ProgramCycleStatus,
                    ProjectStatus, RecognitionTier, RecordStatus,
                    ReferralStatus, RotationStatus, ShiftKind, ShiftStatus,
                    SignupStatus, SourceType, VolunteerStatus)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _parse_instant(ts: str) -> datetime:
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_same_instant(actual: str, expected_iso: str):
    """Assert two ISO 8601 UTC timestamps denote the same instant.

    PRD §2.7: "Timestamps are compared at second precision on ISO 8601 UTC
    values." The PRD pins the instant a logical-clock-derived stamp must
    hold (§2.5) but not its fractional-digit rendering, so comparison is by
    instant, not by string equality.
    """
    assert _parse_instant(actual) == _parse_instant(expected_iso), \
        f"{actual!r} does not denote the same instant as {expected_iso!r}"


def assert_program_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["year_label"], str) and data["year_label"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["admission_capacity"], int) \
        and data["admission_capacity"] >= 1
    assert isinstance(data["accepted_count"], int) \
        and data["accepted_count"] >= 0
    assert isinstance(data["enrolled_count"], int) \
        and data["enrolled_count"] >= 0
    assert isinstance(data["training_module_count"], int) \
        and data["training_module_count"] >= 1
    assert isinstance(data["training_capacity"], int) \
        and data["training_capacity"] >= 1
    assert isinstance(data["priority_counties"], list)
    assert data["status"] in [s.value for s in ProgramCycleStatus]


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data["applicant_name"], str) and data["applicant_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["county"], str) and data["county"]
    assert isinstance(data["prior_gardening_years"], int) \
        and data["prior_gardening_years"] >= 0
    assert data["status"] in [s.value for s in ApplicationStatus]


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in [s.value for s in VolunteerStatus]
    assert isinstance(data["consecutive_shortfall_cycles"], int) \
        and data["consecutive_shortfall_cycles"] >= 0
    assert isinstance(data["no_show_strikes"], int) \
        and data["no_show_strikes"] >= 0
    assert data["recognition_tier"] in [t.value for t in RecognitionTier]
    assert data["lifetime_base_hours"] >= 0.0
    assert data["recognition_points"] >= 0.0


def assert_training_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["modules_completed"], int) \
        and data["modules_completed"] >= 0
    assert 0.0 <= data["quiz_average"] <= 100.0
    assert data["status"] in [s.value for s in EnrollmentStatus]


def assert_credit_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data["entry_kind"] in [k.value for k in EntryKind]
    assert data["status"] in [s.value for s in CreditEntryStatus]
    assert data["source_type"] in [s.value for s in SourceType]
    hours = data["hours"]
    assert hours > 0 and hours <= 12.0, "hours must be in (0, 12.0]"
    quantum = round(hours / 0.25)
    assert abs(hours - quantum * 0.25) < 1e-9, \
        "hours must be a multiple of 0.25"
    if data["entry_kind"] == EntryKind.SERVICE.value:
        assert data["activity_type"] in [a.value for a in ActivityType]
    if data["entry_kind"] == EntryKind.CONTINUING_ED.value:
        assert data.get("provider") and data.get("title")


def assert_recertification_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data["status"] in [s.value for s in RecordStatus]
    assert isinstance(data["hardship_exemption"], bool)
    assert data["provisional_service_hours"] >= 0.0
    assert data["provisional_ce_hours"] >= 0.0
    assert data["official_service_hours"] >= 0.0
    assert data["official_ce_hours"] >= 0.0


def assert_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data["kind"] in [k.value for k in ShiftKind]
    assert isinstance(data["location"], str) and data["location"]
    assert is_iso8601_timestamp(data.get("start_time", ""))
    assert is_iso8601_timestamp(data.get("end_time", ""))
    assert 1 <= data["capacity"] <= 20
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["status"] in [s.value for s in ShiftStatus]


def assert_shift_signup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in [s.value for s in SignupStatus]
    assert is_iso8601_timestamp(data.get("signed_up_at", ""))


def assert_inquiry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("shift_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["subject"], str) and data["subject"]
    assert isinstance(data["contact_name"], str)
    assert isinstance(data["details"], str)
    assert data["status"] in [s.value for s in InquiryStatus]
    assert data["resolution"] in [r.value for r in InquiryResolution]
    if data.get("category") is not None:
        assert data["category"] in [c.value for c in InquiryCategory]


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("inquiry_id", ""))
    assert data["status"] in [s.value for s in ReferralStatus]
    assert isinstance(data["reassignment_count"], int) \
        and data["reassignment_count"] >= 0


def assert_specialist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["specialty"] in [c.value for c in InquiryCategory]
    assert isinstance(data["max_concurrent_referrals"], int) \
        and data["max_concurrent_referrals"] >= 1
    assert isinstance(data["accepting_referrals"], bool)
    for counter in ("open_referral_count", "answered_count",
                    "late_referral_count", "returned_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert 0 <= data["rolling_score"] <= 100
    assert 0 <= data["lifetime_score"] <= 100


def assert_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("organizer_volunteer_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["description"], str)
    assert data["estimated_hours_per_volunteer"] > 0
    assert data["status"] in [s.value for s in ProjectStatus]


def assert_rotation_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bed_code"], str) and data["bed_code"]
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data["week_start"], str)
    assert isinstance(data["week_end"], str)
    assert data["status"] in [s.value for s in RotationStatus]


def assert_shift_seat_invariants(shift: dict):
    """Seat accounting invariant: filled_count never exceeds capacity and a
    FULL shift is exactly at capacity."""
    assert 0 <= shift["filled_count"] <= shift["capacity"]
    if shift["status"] == ShiftStatus.FULL.value:
        assert shift["filled_count"] == shift["capacity"]


def assert_record_totals_consistent(record: dict):
    """Provisional totals are always at least the official totals on the
    same entry history (provisional includes PENDING and applies no caps)."""
    assert record["provisional_service_hours"] \
        >= record["official_service_hours"]
    assert record["provisional_ce_hours"] >= record["official_ce_hours"]
