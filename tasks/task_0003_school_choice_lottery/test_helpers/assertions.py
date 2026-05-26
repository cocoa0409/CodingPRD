"""Entity assertions and domain invariant checkers.

Mirrors the field shapes declared in PRD §3.1–§3.5 and the common envelope
rules in PRD §2.4.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_DISTRICT_STATUSES = {"ACTIVE", "ARCHIVED"}
_SCHOOL_TYPES = {"NEIGHBORHOOD", "MAGNET"}
_WINDOW_STATUSES = {"DRAFT", "OPEN", "CLOSED", "LOTTERY_RUN", "FINALIZED"}
_APPLICATION_STATUSES = {
    "DRAFT", "SUBMITTED", "ACCEPTED", "WAITLISTED", "REJECTED",
    "WITHDRAWN", "OFFERED", "DECLINED", "ENROLLED",
}
_OFFER_STATUSES = {"OFFERED", "ACCEPTED", "DECLINED", "EXPIRED"}
_OFFER_SOURCES = {"LOTTERY", "WAITLIST_PROMOTION"}
_WAITLIST_STATUSES = {"ACTIVE", "PROMOTED", "REMOVED"}


def _assert_common_fields(data: dict, label: str) -> None:
    """PRD §2.4: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer (got {data.get('version')!r})"
    )


def _assert_append_only_fields(data: dict, label: str) -> None:
    """PRD §2.4 — append-only resources (SiblingBond, SystemClock): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )


def assert_district(data: dict) -> None:
    _assert_common_fields(data, "District")
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 8
    assert isinstance(data["name"], str)
    assert isinstance(data["poverty_index_pct"], (int, float))
    assert 0 <= data["poverty_index_pct"] <= 100
    assert data["status"] in _DISTRICT_STATUSES


def assert_school(data: dict) -> None:
    _assert_common_fields(data, "School")
    assert is_valid_uuid(data["district_id"])
    assert isinstance(data["code"], str) and 3 <= len(data["code"]) <= 12
    assert isinstance(data["name"], str)
    assert data["school_type"] in _SCHOOL_TYPES
    assert isinstance(data["grade_min"], int) and 0 <= data["grade_min"]
    assert isinstance(data["grade_max"], int) and data["grade_max"] <= 12
    assert data["grade_min"] <= data["grade_max"]
    assert isinstance(data["total_seats"], int) and data["total_seats"] >= 0


def assert_boundary_rule(data: dict) -> None:
    _assert_common_fields(data, "BoundaryRule")
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["zone_code"], str)
    assert isinstance(data["is_in_boundary"], bool)


def assert_enrollment_window(data: dict) -> None:
    _assert_common_fields(data, "EnrollmentWindow")
    assert is_valid_uuid(data["district_id"])
    assert isinstance(data["cycle_label"], str)
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert is_iso8601_timestamp(data["lottery_runs_at"])
    assert data["status"] in _WINDOW_STATUSES


def assert_family(data: dict) -> None:
    _assert_common_fields(data, "Family")
    assert isinstance(data["guardian_email"], str)
    assert isinstance(data["residence_zone_code"], str)
    assert is_valid_uuid(data["residence_district_id"])
    assert isinstance(data["poverty_flag"], bool)


def assert_student(data: dict) -> None:
    _assert_common_fields(data, "Student")
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["grade_for_cycle"], int)
    assert 0 <= data["grade_for_cycle"] <= 12


def assert_application(data: dict) -> None:
    _assert_common_fields(data, "Application")
    assert is_valid_uuid(data["window_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["choice_rank"], int) and 1 <= data["choice_rank"] <= 5
    assert data["status"] in _APPLICATION_STATUSES


def assert_offer(data: dict) -> None:
    _assert_common_fields(data, "Offer")
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in _OFFER_STATUSES
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["respond_by"])
    assert data["source"] in _OFFER_SOURCES


def assert_waitlist_entry(data: dict) -> None:
    _assert_common_fields(data, "WaitlistEntry")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["school_id"])
    assert isinstance(data["queue_rank"], int) and data["queue_rank"] >= 1
    assert data["status"] in _WAITLIST_STATUSES


def assert_sibling_bond(data: dict) -> None:
    """PRD §2.4: append-only — id + created_at only."""
    _assert_append_only_fields(data, "SiblingBond")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["sibling_student_id"])
    assert is_valid_uuid(data["school_id"])


def assert_three_decimal_score(value, label: str = "score") -> None:
    """PRD §2.8: scores are reported to three decimal places (half-up)."""
    assert isinstance(value, (int, float)), (
        f"{label} must be numeric, got {type(value).__name__}"
    )
    # rounding-to-three is what we assert; we allow tiny float wiggle.
    rounded = round(float(value), 3)
    assert abs(float(value) - rounded) < 1e-9, (
        f"{label} must be rounded to three decimals (got {value!r})"
    )
