"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Every resource carries the common system-managed properties of PRD §2.5
(id UUID, created_at/updated_at ISO 8601, integer version). The per-entity
assertions below validate those plus the entity's own fields and status
domains.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating optional fractional digits."""
    assert isinstance(value, str), f"expected ISO 8601 string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_instant_equal(actual: str, expected: str):
    """Two ISO 8601 strings denote the same instant (fractional-digit shape may
    differ between serializers; the PRD pins instants, not rendering)."""
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common_fields(data: dict):
    """PRD §2.5 system-managed properties present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_exam_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("SETUP", "OPEN")
    for field in (
        "registration_deadline_at",
        "order_deadline_at",
        "score_release_at",
        "exam_window_start_at",
        "exam_window_end_at",
    ):
        assert is_iso8601_timestamp(data[field]), f"{field} must be ISO 8601"
    for field in (
        "late_fee_cents",
        "unused_exam_penalty_cents",
        "fee_reduction_cents",
        "budget_cap_cents",
        "rebate_rate_bp",
        "registered_exam_count",
        "rebate_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["late_fee_cents"] >= 0
    assert data["unused_exam_penalty_cents"] >= 0
    assert data["fee_reduction_cents"] >= 0
    assert data["budget_cap_cents"] >= 0
    assert 0 <= data["rebate_rate_bp"] <= 10000


def assert_course(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["subject_code"], str) and data["subject_code"]
    assert data["program"] in ("AP", "IB")
    assert isinstance(data["exam_fee_cents"], int) and data["exam_fee_cents"] > 0
    assert isinstance(data["credit_threshold"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["authorized_teacher_count"], int)
    assert data["authorized_teacher_count"] >= 0
    assert isinstance(data["registered_count"], int)
    assert data["registered_count"] >= 0


def assert_teacher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_teacher_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["teacher_id"])
    assert is_valid_uuid(data["course_id"])
    assert data["status"] in ("PENDING_TRAINING", "AUTHORIZED", "EXPIRED")
    assert data["training_completed_at"] is None or is_iso8601_timestamp(
        data["training_completed_at"]
    )
    assert data["authorized_until"] is None or is_iso8601_timestamp(
        data["authorized_until"]
    )


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["grade_level"], int)
    assert 9 <= data["grade_level"] <= 12
    assert data["subgroup_code"] in ("GEN", "FRL", "IEP", "ELL")
    for field in ("balance_cents", "projected_balance_cents", "transcript_posted_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_fee_reduction_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["cycle_id"])
    assert data["eligibility_basis"] in (
        "FREE_LUNCH",
        "REDUCED_LUNCH",
        "INCOME",
        "OTHER",
    )
    assert isinstance(data["annual_income_cents"], int)
    assert data["annual_income_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_exam_registration(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["cycle_id"])
    assert data["accommodation_type"] in ("NONE", "EXTENDED_TIME", "SEPARATE_ROOM")
    assert data["registration_status"] in (
        "REGISTERED",
        "SAT",
        "NO_SHOW",
        "CANCELLED",
    )
    assert data["score_status"] in (
        "PENDING",
        "HELD",
        "RELEASED",
        "POSTED",
        "NO_SCORE",
        "VOID",
    )
    assert data["score"] is None or isinstance(data["score"], int)
    assert isinstance(data["is_late"], bool)
    for field in (
        "fee_cents",
        "late_fee_applied_cents",
        "subsidy_cents",
        "net_fee_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    # PRD §3.3: net fee is always at least 0 because the subsidy is capped.
    assert data["net_fee_cents"] >= 0
    assert data["net_fee_cents"] == (
        data["fee_cents"] + data["late_fee_applied_cents"] - data["subsidy_cents"]
    ), "net_fee_cents must equal fee + late - subsidy"


def assert_exam_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["cycle_id"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED", "RECONCILED")
    assert isinstance(data["adjustments"], list)
    for adjustment in data["adjustments"]:
        assert is_valid_uuid(adjustment["course_id"])
        assert isinstance(adjustment["delta"], int)
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line["course_id"])
        assert isinstance(line["ordered_count"], int)
        assert isinstance(line["fee_cents"], int)
        assert isinstance(line["late_fee_total_cents"], int)
        assert isinstance(line["line_total_cents"], int)
    assert isinstance(data["estimate_total_cents"], int)
    assert data["final_total_cents"] is None or isinstance(
        data["final_total_cents"], int
    )
    assert data["submitted_late"] is None or isinstance(data["submitted_late"], bool)
    for field in ("submitted_at", "locked_at", "reconciled_at"):
        assert data[field] is None or is_iso8601_timestamp(data[field])


def assert_exam_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert isinstance(data["room_name"], str) and data["room_name"]
    assert isinstance(data["room_capacity"], int) and data["room_capacity"] > 0
    assert isinstance(data["room_supports_accommodations"], bool)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in (
        "SCHEDULED",
        "ADMINISTERED",
        "UNDER_INVESTIGATION",
        "INVALIDATED",
        "CANCELLED",
    )
    assert isinstance(data["seats_reserved"], int) and data["seats_reserved"] >= 0


def assert_proctor_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["teacher_id"])
    assert data["status"] in ("ASSIGNED", "RELEASED")


def assert_irregularity_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["proctor_teacher_id"])
    assert data["category"] in (
        "SECURITY_BREACH",
        "TIMING_ERROR",
        "ACCOMMODATION_VIOLATION",
        "MISCONDUCT",
        "MATERIALS",
    )
    assert isinstance(data["details"], str)
    assert data["status"] in ("FILED", "RESOLVED", "SCORES_CANCELLED")


def assert_student_statement(data: dict):
    assert is_valid_uuid(data["student_id"])
    for field in ("balance_cents", "projected_balance_cents", "transcript_posted_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["balance_cents"] >= 0
    assert data["projected_balance_cents"] >= 0
