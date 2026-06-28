"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_LEVELS = ["TODDLER", "PRIMARY", "ELEMENTARY"]


def _assert_common(data: dict):
    """id + created_at + updated_at + version (every entity except Observation)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_tuition_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["level"] in _LEVELS
    assert isinstance(data["base_annual_cents"], int) and data["base_annual_cents"] >= 0
    assert 0 <= data["deposit_pct"] <= 1
    assert 1 <= data["installments"] <= 12
    assert isinstance(data["extended_day_annual_cents"], int)
    assert data["extended_day_annual_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_classroom(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["level"] in _LEVELS
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["min_age_months"], int) and data["min_age_months"] >= 0
    assert isinstance(data["max_age_months"], int)
    assert data["max_age_months"] >= data["min_age_months"]
    assert isinstance(data["placed_count"], int) and data["placed_count"] >= 0
    assert isinstance(data["assigned_staff_count"], int) and data["assigned_staff_count"] >= 0
    assert data["compliance_status"] in ["COMPLIANT", "OVER_RATIO", "OVER_CAPACITY"]


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["parent_user_id"], str) and len(data["parent_user_id"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["date_of_birth"])
    assert isinstance(data["staff_child"], bool)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["classroom_id"])
    assert is_valid_uuid(data["tier_id"])
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "CHANGES_REQUESTED", "WAITLISTED",
        "OFFERED", "ENROLLED", "WITHDRAWN", "DECLINED",
    ]
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["extended_day_opt_in"], bool)
    assert 0 <= data["financial_aid_pct"] < 1


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["classroom_id"])
    assert is_valid_uuid(data["tier_id"])
    assert data["placement_status"] in ["PLACED", "ON_LEAVE", "WITHDRAWN"]
    assert data["billing_status"] in ["DEPOSIT_DUE", "ACTIVE", "PAST_DUE", "SETTLED"]
    assert isinstance(data["extended_day_opt_in"], bool)
    assert is_iso8601_timestamp(data["program_start_date"])
    assert isinstance(data["net_annual_cents"], int) and data["net_annual_cents"] >= 0
    assert isinstance(data["monthly_installment_cents"], int)
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["paid_to_date_cents"], int) and data["paid_to_date_cents"] >= 0


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["kind"] in ["DEPOSIT", "INSTALLMENT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["status"] in ["CAPTURED", "REFUNDED"]


def assert_refund_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_iso8601_timestamp(data["effective_date"])
    assert data["method"] in ["FORWARD", "CHRONOLOGICAL"]
    assert data["status"] in ["COMPUTED", "APPROVED", "PAID", "VOID"]
    assert isinstance(data["earned_cents"], int) and data["earned_cents"] >= 0
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0
    assert isinstance(data["balance_due_cents"], int) and data["balance_due_cents"] >= 0


def assert_staff_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["classroom_id"])
    assert isinstance(data["staff_name"], str) and len(data["staff_name"]) > 0
    assert data["status"] in ["ACTIVE", "ENDED"]


def assert_assessment_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["work_area"] in [
        "PRACTICAL_LIFE", "SENSORIAL", "LANGUAGE", "MATHEMATICS", "CULTURAL",
    ]
    assert data["mastery_level"] in ["INTRODUCED", "PRACTICING", "MASTERED"]
    assert is_iso8601_timestamp(data["work_cycle_date"])
    assert isinstance(data["portfolio_included"], bool)


def assert_conference_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["guide_user_id"], str) and len(data["guide_user_id"]) > 0
    assert is_valid_uuid(data["classroom_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in ["OPEN", "BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED"]


def assert_observation(data: dict):
    """Observation is immutable: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["classroom_id"])
    assert isinstance(data["observer_name"], str) and len(data["observer_name"]) > 0
    assert is_iso8601_timestamp(data["window_start_at"])
    assert is_iso8601_timestamp(data["window_end_at"])


def assert_refund_conservation(paid_before: int, paid_after: int, refund_cents: int):
    """Money conservation invariant (PRD §3.9): the new paid-to-date equals the prior
    paid-to-date less the refunded amount, with no cents drift."""
    assert paid_after == paid_before - refund_cents, (
        f"Money not conserved: {paid_before} - {refund_cents} != {paid_after}"
    )
