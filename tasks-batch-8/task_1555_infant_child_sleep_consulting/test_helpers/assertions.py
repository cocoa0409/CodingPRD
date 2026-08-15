"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgeBand,
    CaseStatus,
    DeliveryMode,
    EnrollmentStatus,
    LogReviewStatus,
    MessageStatus,
    PackageKind,
    PackageStatus,
    PackageTier,
    PlanMethod,
    PlanStatus,
    QuestionnaireStatus,
    RefundStatus,
    RefundType,
    SessionStatus,
    SessionType,
)


def _assert_bookkeeping(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_consultant(data: dict):
    """Validate a Consultant response against the PRD contract."""
    _assert_bookkeeping(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["certification_no"], str) and data["certification_no"]
    assert isinstance(data["max_active_cases"], int) and data["max_active_cases"] >= 1
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0


def assert_family(data: dict):
    """Validate a ClientFamily response against the PRD contract."""
    _assert_bookkeeping(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0, "family credit balance never goes negative"
    assert isinstance(data["is_repeat_client"], bool)


def assert_case(data: dict):
    """Validate a ClientCase response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["family_id"])
    assert is_valid_uuid(data["consultant_id"])
    assert isinstance(data["child_birth_date"], str)
    assert data["delivery_mode"] in _values(DeliveryMode)
    assert isinstance(data["guarantee_goal_night_wakings"], int)
    assert data["guarantee_goal_night_wakings"] >= 0
    assert isinstance(data["child_age_months"], int) and data["child_age_months"] >= 0
    assert data["age_band"] in _values(AgeBand)
    assert data["status"] in _values(CaseStatus)
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_questionnaire(data: dict):
    """Validate an IntakeQuestionnaire response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["answers"], dict)
    assert isinstance(data["provisional_severity_score"], int)
    assert 0 <= data["provisional_severity_score"] <= 100
    assert data["status"] in _values(QuestionnaireStatus)
    assert data.get("adjustment_points") is None or isinstance(data["adjustment_points"], int)
    assert data.get("reviewed_severity_score") is None or isinstance(
        data["reviewed_severity_score"], int
    )
    assert data.get("review_note") is None or isinstance(data["review_note"], str)


def assert_plan(data: dict):
    """Validate a SleepPlan response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["plan_sequence"], int) and data["plan_sequence"] >= 1
    assert data["age_band"] in _values(AgeBand)
    assert data["method"] in _values(PlanMethod)
    assert isinstance(data["target_night_wake_count"], int)
    assert data["target_night_wake_count"] >= 0
    assert isinstance(data["target_longest_stretch_minutes"], int)
    assert data["target_longest_stretch_minutes"] > 0
    assert data.get("notes") is None or isinstance(data["notes"], str)
    assert data["status"] in _values(PlanStatus)


def assert_package(data: dict):
    """Validate a SupportPackage response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert data["tier"] in _values(PackageTier)
    assert data["kind"] in _values(PackageKind)
    assert is_iso8601_timestamp(data["purchased_at"])
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["duration_weeks"], int) and data["duration_weeks"] >= 1
    assert isinstance(data["expires_on"], str)
    assert isinstance(data["included_calls"], int) and data["included_calls"] >= 0
    assert isinstance(data["included_messages"], int) and data["included_messages"] >= 0
    assert isinstance(data["response_sla_hours"], int) and data["response_sla_hours"] > 0
    assert isinstance(data["gross_price_cents"], int)
    assert isinstance(data["repeat_discount_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["net_price_cents"], int)
    assert isinstance(data["sla_credit_total_cents"], int)
    assert data["status"] in _values(PackageStatus)
    assert_package_entitlement_invariants(data)


def assert_package_entitlement_invariants(data: dict):
    """Entitlement-ledger invariants that must hold on every package read."""
    assert data["remaining_calls"] >= 0, "remaining_calls never goes negative"
    assert data["remaining_messages"] >= 0, "remaining_messages never goes negative"
    assert data["remaining_calls"] <= data["included_calls"]
    assert data["remaining_messages"] <= data["included_messages"]


def assert_log(data: dict):
    """Validate a NightlySleepLog response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["log_date"], str)
    for field in ("night_wake_count", "longest_stretch_minutes", "nap_count", "nap_total_minutes"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data.get("notes") is None or isinstance(data["notes"], str)
    assert data["review_status"] in _values(LogReviewStatus)
    assert data.get("review_note") is None or isinstance(data["review_note"], str)


def assert_session(data: dict):
    """Validate a TroubleshootingSession response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["package_id"])
    assert data["session_type"] in _values(SessionType)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in _values(SessionStatus)


def assert_message(data: dict):
    """Validate a Message response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["package_id"])
    assert isinstance(data["body"], str)
    assert data.get("response_body") is None or isinstance(data["response_body"], str)
    assert data.get("first_responded_at") is None or is_iso8601_timestamp(
        data["first_responded_at"]
    )
    assert data.get("sla_breached") is None or isinstance(data["sla_breached"], bool)
    assert data.get("credit_granted_cents") is None or isinstance(
        data["credit_granted_cents"], int
    )
    assert data["status"] in _values(MessageStatus)


def assert_refund_request(data: dict):
    """Validate a RefundRequest response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["package_id"])
    assert data["refund_type"] in _values(RefundType)
    assert data.get("reason") is None or isinstance(data["reason"], str)
    assert data.get("amount_cents") is None or isinstance(data["amount_cents"], int)
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)
    assert data["status"] in _values(RefundStatus)


def assert_course(data: dict):
    """Validate a GroupCourse response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["consultant_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_enrollment(data: dict):
    """Validate a CourseEnrollment response against the PRD contract."""
    _assert_bookkeeping(data)
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["case_id"])
    assert data["status"] in _values(EnrollmentStatus)
    assert data.get("promoted_at") is None or is_iso8601_timestamp(data["promoted_at"])
