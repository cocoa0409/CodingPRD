"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

COURSE_STATUSES = ["DRAFT", "PUBLISHED", "RETIRED"]
COHORT_STATUSES = ["DRAFT", "SCHEDULED", "IN_SESSION", "CONCLUDED", "CANCELLED"]
ENROLLMENT_STATUSES = ["PENDING_PAYMENT", "ACTIVE", "WAITLISTED", "COMPLETED", "CANCELLED"]
GUARANTEE_STATUSES = ["PENDING", "ELIGIBLE", "INELIGIBLE", "REFUND_ISSUED", "RETAKE_GRANTED"]
ATTEMPT_STATUSES = ["STARTED", "COMPLETED", "VOIDED"]
ATTEMPT_TYPES = ["DIAGNOSTIC", "PRACTICE"]
PLAN_STATUSES = ["OPEN", "PAID_IN_FULL", "DEFAULTED", "REFUNDED"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "APPROVED", "REJECTED"]
EXAM_TYPES = ["SAT", "ACT", "MCAT", "LSAT"]
FORMATS = ["LIVE", "ONLINE", "SELF"]


def _assert_common_fields(data: dict):
    """Common server-managed fields for entities with common_fields:true (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments on mutation"


def assert_course(data: dict):
    _assert_common_fields(data)
    assert data["exam_type"] in EXAM_TYPES, f"exam_type {data['exam_type']!r} not in {EXAM_TYPES}"
    assert data["format"] in FORMATS, f"format {data['format']!r} not in {FORMATS}"
    assert isinstance(data["title"], str)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["baseline_scale_max"], int) and data["baseline_scale_max"] > 0
    assert isinstance(data["guarantee_min_delta"], int) and data["guarantee_min_delta"] >= 0
    assert isinstance(data["required_practice_tests"], int) and data["required_practice_tests"] >= 0
    assert 0.0 <= data["required_attendance_pct"] <= 1.0
    assert isinstance(data["materials_access_days"], int) and data["materials_access_days"] > 0
    assert data["status"] in COURSE_STATUSES


def assert_instructor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certified_exam_types"], list) and len(data["certified_exam_types"]) >= 1
    for e in data["certified_exam_types"]:
        assert e in EXAM_TYPES
    assert isinstance(data["max_concurrent_cohorts"], int) and data["max_concurrent_cohorts"] >= 1
    assert isinstance(data["active_cohort_count"], int) and data["active_cohort_count"] >= 0


def assert_cohort(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["course_id"])
    assert data["instructor_id"] is None or is_valid_uuid(data["instructor_id"])
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["seats_committed"], int) and data["seats_committed"] >= 0
    assert data["seats_committed"] <= data["seat_capacity"], "seats_committed never exceeds seat_capacity"
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert isinstance(data["total_sessions"], int) and data["total_sessions"] >= 1
    assert data["status"] in COHORT_STATUSES


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert data["diagnostic_score"] is None or isinstance(data["diagnostic_score"], int)


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["cohort_id"])
    assert data["status"] in ENROLLMENT_STATUSES
    assert isinstance(data["price_paid_cents"], int) and data["price_paid_cents"] >= 0
    assert isinstance(data["completed_practice_count"], int) and data["completed_practice_count"] >= 0
    assert isinstance(data["sessions_attended"], int) and data["sessions_attended"] >= 0
    assert data["best_practice_score"] is None or isinstance(data["best_practice_score"], int)
    assert data["guarantee_status"] in GUARANTEE_STATUSES
    assert data["materials_expire_at"] is None or is_iso8601_timestamp(data["materials_expire_at"])
    assert data["waitlist_seq"] is None or (isinstance(data["waitlist_seq"], int) and data["waitlist_seq"] >= 1)


def assert_practice_attempt(data: dict):
    """PracticeAttempt has common_fields:false — id + created_at only,
    NO version, NO updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["enrollment_id"])
    assert data["attempt_type"] in ATTEMPT_TYPES
    assert isinstance(data["raw_correct"], int) and data["raw_correct"] >= 0
    assert isinstance(data["total_items"], int) and data["total_items"] >= 1
    assert data["raw_correct"] <= data["total_items"]
    assert data["status"] in ATTEMPT_STATUSES
    if data["status"] == "COMPLETED":
        assert isinstance(data["scaled_score"], int)


def assert_practice_attempt_has_no_version(data: dict):
    """PRD §2.4: a PracticeAttempt 'has no updated_at and no version field'."""
    assert "version" not in data, "PracticeAttempt response must not carry a 'version' field"
    assert "updated_at" not in data, "PracticeAttempt response must not carry an 'updated_at' field"


def assert_installment_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["num_installments"] in [1, 2, 3, 4, 6, 12]
    assert isinstance(data["total_financed_cents"], int) and data["total_financed_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data["status"] in PLAN_STATUSES


def assert_guarantee_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["resolution"] in ["REFUND", "RETAKE"]
    assert data["improvement_delta"] is None or isinstance(data["improvement_delta"], int)
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert data["status"] in CLAIM_STATUSES


# --- Domain invariant checkers ---

def assert_seat_invariant(cohort: dict):
    """PRD §3.1: seats_committed 'never exceeds seat_capacity'."""
    assert 0 <= cohort["seats_committed"] <= cohort["seat_capacity"], (
        f"seat invariant violated: seats_committed={cohort['seats_committed']}, "
        f"seat_capacity={cohort['seat_capacity']}"
    )


def assert_money_conserved(refund_amount_cents: int, collected_cents: int):
    """PRD §3.6: 'money returned equals money collected for the enrollment.'"""
    assert refund_amount_cents == collected_cents, (
        f"money not conserved: returned={refund_amount_cents}, collected={collected_cents}"
    )
