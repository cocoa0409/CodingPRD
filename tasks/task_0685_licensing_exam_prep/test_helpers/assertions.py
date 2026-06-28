"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. QuestionItem carries ONLY id + created_at (immutable
content with no version), so its assertion never demands updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version quartet (every entity except QuestionItem)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_license_program(data: dict):
    _assert_common(data)
    assert isinstance(data["license_code"], str) and len(data["license_code"]) > 0
    assert isinstance(data["title"], str)
    assert 0 <= data["passing_scaled_score"] <= 100
    assert isinstance(data["domain_weights"], list) and len(data["domain_weights"]) >= 1
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_subscription_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "PRO")
    assert isinstance(data["total_price_cents"], int) and data["total_price_cents"] >= 0
    assert 0.0 <= data["down_payment_pct"] <= 1.00
    assert 1 <= data["financing_months"] <= 24
    assert data["included_mock_credits"] >= 0
    assert isinstance(data["pass_guarantee"], bool)
    assert 0.0 <= data["guarantee_refund_pct"] <= 1.00
    assert isinstance(data["includes_ce"], bool)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_ce_bundle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_program_id"])
    assert data["ce_credits_total"] >= 1
    assert data["modules_total"] >= 1


def assert_question_item(data: dict):
    """common_fields:false — id + created_at ONLY; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["license_program_id"])
    assert isinstance(data["domain_code"], str) and len(data["domain_code"]) > 0
    assert data["difficulty"] in ("EASY", "MEDIUM", "HARD")
    assert isinstance(data["correct_choice"], str)


def assert_cohort(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_program_id"])
    assert isinstance(data["title"], str)
    assert data["capacity"] >= 1
    assert data["seats_taken"] >= 0
    assert data["status"] in ("OPEN", "FULL", "CLOSED")


def assert_cohort_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cohort_id"])
    assert isinstance(data["topic"], str)
    assert is_iso8601_timestamp(data["session_start_utc"])
    assert is_iso8601_timestamp(data["session_end_utc"])


def assert_learner(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["learner_id"])
    assert is_valid_uuid(data["license_program_id"])
    assert is_valid_uuid(data["subscription_plan_id"])
    assert isinstance(data["financed"], bool)
    assert isinstance(data["financing_total_due_cents"], int)
    assert isinstance(data["financing_paid_cents"], int)
    assert isinstance(data["financing_balance_cents"], int)
    assert data["financing_balance_cents"] >= 0, "financing_balance_cents floored at 0"
    assert isinstance(data["questions_answered_total"], int)
    assert isinstance(data["completed_mock_count"], int)
    assert 0 <= data["readiness_score"] <= 100
    assert 0 <= data["projected_readiness_score"] <= 100
    assert data["exam_outcome"] in ("PENDING", "PASS", "FAIL")
    assert isinstance(data["guarantee_eligible"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "PASSED", "FAILED", "REFUNDED", "WITHDRAWN")


def assert_installment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("DUE", "PAID", "VOID")


def assert_study_plan_domain(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["domain_code"], str)
    assert 0 <= data["mastery"] <= 100


def assert_practice_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert isinstance(data["domain_code"], str)
    assert data["answered_count"] >= 0
    assert 0 <= data["correct_count"] <= data["answered_count"]
    assert 0 <= data["batch_pct"] <= 100
    assert data["status"] == "COMPLETED"


def assert_mock_exam(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["raw_score"] >= 0
    assert data["item_count"] >= 1
    assert 0 <= data["scaled_score"] <= 100
    assert isinstance(data["is_overage"], bool)
    assert is_iso8601_timestamp(data["completed_at"])
    assert data["status"] == "COMPLETED"


def assert_pass_guarantee_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["remedy"] in ("RETAKE_EXTENSION", "MONEY_BACK")
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")


def assert_ce_credit_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["ce_bundle_id"])
    assert data["modules_completed"] >= 1
    assert isinstance(data["credits_awarded"], int)
    assert isinstance(data["cumulative_credits"], int)


def assert_cohort_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cohort_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["status"] in ("JOINED", "DROPPED")


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_financing_invariants(enrollment: dict):
    """Ledger invariants that must hold on any enrollment (§3.2, §2.8)."""
    assert enrollment["financing_balance_cents"] >= 0, "balance floored at 0"
    assert enrollment["financing_balance_cents"] == (
        enrollment["financing_total_due_cents"] - enrollment["financing_paid_cents"]
        if enrollment["financing_total_due_cents"] - enrollment["financing_paid_cents"] >= 0
        else 0
    ), "financing_balance_cents == total_due - paid (floored at 0)"
