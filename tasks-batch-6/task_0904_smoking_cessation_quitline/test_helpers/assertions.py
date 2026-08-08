"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_employer_program(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["nrt_courses_allotted"], int)


def assert_coach(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["languages"], list)


def assert_participant(data: dict):
    _assert_versioned(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["primary_language"], str)
    assert isinstance(data["cigarettes_per_day"], int)


def assert_enrollment(data: dict):
    _assert_versioned(data)
    assert data["status"] in (
        "PENDING_ASSESSMENT", "ACTIVE", "DISENROLLED", "COMPLETED", "DECLINED"
    )
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["nrt_courses_allotted"], int)
    assert isinstance(data["nrt_courses_used"], int)
    assert data["nrt_eligibility"] in ("ELIGIBLE", "EXHAUSTED")


def assert_quit_attempt(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("COMMITTED", "QUIT_ACHIEVED", "RELAPSED", "ABANDONED")
    assert data["method"] in (
        "COLD_TURKEY", "NRT_ASSISTED", "MEDICATION", "GRADUAL_REDUCTION"
    )
    assert isinstance(data["attempt_number"], int)


def assert_coaching_call(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELED")
    assert isinstance(data["coach_id"], str)


def assert_nrt_shipment(data: dict):
    _assert_versioned(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "SHIPPED", "DELIVERED", "CANCELED", "RETURNED"
    )
    assert data["medication_type"] in (
        "PATCH", "GUM", "LOZENGE", "VARENICLINE", "BUPROPION"
    )


def assert_incentive_award(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("EARNED", "PAID", "FORFEITED")
    assert data["source"] in ("SYSTEM", "MANUAL")
    assert isinstance(data["amount_cents"], int)


def assert_referral(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["referral_type"] in ("PROVIDER", "BENEFIT", "PHARMACY")


def assert_readiness_assessment(data: dict):
    """Append-only event: only id + created_at, plus computed fields."""
    _assert_common(data)
    assert "version" not in data, "ReadinessAssessment is append-only; no version"
    assert "updated_at" not in data, "ReadinessAssessment is append-only; no updated_at"
    assert isinstance(data["readiness_score"], int)
    assert data["result"] in ("PASS", "FAIL")


def assert_follow_up_outcome(data: dict):
    """Append-only event: only id + created_at."""
    _assert_common(data)
    assert "version" not in data, "FollowUpOutcome is append-only; no version"
    assert "updated_at" not in data, "FollowUpOutcome is append-only; no updated_at"
    assert data["day"] in (7, 30)
    assert isinstance(data["abstinent"], bool)
