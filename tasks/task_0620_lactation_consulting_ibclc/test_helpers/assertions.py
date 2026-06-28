"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate the response structure against the PRD
contract; invariant checkers verify cross-field rules that must always hold.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_full_resource_envelope(data: dict):
    """Full resources carry id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lightweight_envelope(data: dict):
    """Immutable records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_practice(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["aca_preventive_enabled"], bool)
    assert is_iso8601_timestamp(data["now_utc"]), "now_utc must be ISO 8601"


def assert_sliding_scale_tier(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["income_ceiling_cents"], int)
    assert isinstance(data["discount_pct"], int)
    assert 0 <= data["discount_pct"] <= 100


def assert_service_package(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["included_visits"], int) and data["included_visits"] >= 1
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["per_visit_value_cents"], int)


def assert_consultant(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["standard_rate_cents"], int)
    assert isinstance(data["travel_buffer_minutes"], int)


def assert_client(data: dict):
    _assert_full_resource_envelope(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["package_credits_total"], int)
    assert isinstance(data["package_credits_consumed"], int)
    assert isinstance(data["package_credits_remaining"], int)
    assert isinstance(data["reimbursement_ledger_cents"], int)
    assert isinstance(data["no_show_strikes"], int)
    assert_client_credit_invariant(data)


def assert_client_credit_invariant(data: dict):
    """PRD §3.2: total == consumed + remaining, and remaining never negative."""
    assert data["package_credits_remaining"] >= 0, "package_credits_remaining must never go negative"
    assert (data["package_credits_total"]
            == data["package_credits_consumed"] + data["package_credits_remaining"]), (
        "package_credits_total must equal consumed + remaining"
    )


def assert_consult(data: dict):
    _assert_full_resource_envelope(data)
    assert data["consult_type"] in ("PRENATAL", "IN_HOME", "TELEHEALTH")
    assert data["pay_method"] in ("SELF_PAY", "PACKAGE")
    assert data["status"] in (
        "SCHEDULED", "RESCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW"
    )
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["package_credit_redeemed"], bool)
    assert isinstance(data["reschedule_count"], int)


def assert_follow_up_plan(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["target_daily_transfer_grams"], int)
    assert isinstance(data["avg_transfer_grams"], int)
    assert isinstance(data["total_transfer_grams"], int)
    assert isinstance(data["meets_target"], bool)


def assert_superbill(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "VOID")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["is_aca_preventive"], bool)
    assert isinstance(data["reimbursed_amount_cents"], int)
    assert isinstance(data["patient_responsibility_cents"], int)


def assert_dme_qualification(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("PENDING", "QUALIFIED", "DENIED")
    assert data["pump_type"] in ("STANDARD_ELECTRIC", "HOSPITAL_GRADE")
    assert isinstance(data["qualified"], bool)


def assert_pediatrician_referral(data: dict):
    _assert_full_resource_envelope(data)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "CANCELLED")
    assert data["reason"] in ("WEIGHT_CONCERN", "TONGUE_TIE", "JAUNDICE", "OTHER")
    assert isinstance(data["pediatrician_name"], str) and len(data["pediatrician_name"]) > 0


def assert_feeding_assessment(data: dict):
    _assert_lightweight_envelope(data)
    assert "updated_at" not in data, "FeedingAssessment is immutable; no updated_at"
    assert "version" not in data, "FeedingAssessment is immutable; no version"
    assert isinstance(data["latch_score"], int)


def assert_weighted_feed(data: dict):
    _assert_lightweight_envelope(data)
    assert "updated_at" not in data, "WeightedFeed is immutable; no updated_at"
    assert "version" not in data, "WeightedFeed is immutable; no version"
    assert isinstance(data["transfer_grams"], int)
