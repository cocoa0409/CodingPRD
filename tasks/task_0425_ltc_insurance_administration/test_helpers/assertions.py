"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp).
Append-only entities (BenefitTriggerCertification, BenefitLedgerEntry) carry
only id + created_at; their assertions deliberately do NOT require updated_at
or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (mutable, versioned entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only_fields(data: dict):
    """id + created_at only (append-only event records)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_policyholder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["medicaid_state_eligible"], bool)


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["product_mode"] in ("REIMBURSEMENT", "INDEMNITY")
    assert data["inflation_rider"] in ("NONE", "COMPOUND_3PCT", "COMPOUND_5PCT")
    assert data["coverage_status"] in (
        "APPLIED", "IN_FORCE", "CLAIM_OPEN", "EXHAUSTED", "RESCINDED")
    assert data["premium_status"] in (
        "PENDING", "PAID_CURRENT", "GRACE", "LAPSED", "NONFORFEITURE_PAID_UP", "WAIVED")
    assert isinstance(data["daily_benefit_max_cents"], int)
    assert isinstance(data["monthly_benefit_max_cents"], int)
    assert isinstance(data["initial_pool_cents"], int)
    assert isinstance(data["elimination_period_days"], int)
    assert isinstance(data["is_partnership_policy"], bool)
    assert isinstance(data["inflation_years_elapsed"], int)
    assert isinstance(data["inflated_daily_max_cents"], int)
    assert isinstance(data["inflated_monthly_max_cents"], int)
    assert isinstance(data["benefits_triggered"], bool)
    assert isinstance(data["elimination_days_satisfied"], int)


def assert_benefit_pool(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["inflated_pool_cents"], int)
    assert isinstance(data["lifetime_paid_cents"], int)
    assert isinstance(data["nonforfeiture_reduction_cents"], int)
    assert isinstance(data["remaining_pool_cents"], int)
    assert data["remaining_pool_cents"] >= 0, "remaining_pool_cents is floored at 0"


def assert_premium_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "WAIVED", "DEFAULTED")


def assert_rate_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["requested_increase_pct"], int)
    assert isinstance(data["approved_increase_pct"], int)
    assert isinstance(data["effective_period_index"], int)
    assert data["status"] in (
        "FILED", "APPROVED", "PARTIALLY_APPROVED", "REJECTED", "WITHDRAWN")


def assert_provider(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["provider_type"] in (
        "NURSING_HOME", "ASSISTED_LIVING", "HOME_HEALTH_AGENCY",
        "ADULT_DAY_CARE", "INFORMAL_CAREGIVER")
    assert isinstance(data["license_active"], bool)
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "INELIGIBLE", "SUSPENDED")


def assert_care_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["provider_id"], str)
    assert data["care_setting"] in (
        "NURSING_HOME", "ASSISTED_LIVING", "HOME_HEALTH", "ADULT_DAY", "INFORMAL")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "CLOSED")


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["care_plan_id"], str)
    assert isinstance(data["service_month"], str)
    assert isinstance(data["month_paid_cents"], int)
    assert isinstance(data["requires_reassessment"], bool)
    assert data["status"] in (
        "SUBMITTED", "UNDER_REVIEW", "PENDING_REASSESSMENT", "APPROVED", "DENIED", "VOID")


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["billed_charge_cents"], int)
    assert isinstance(data["is_qualifying_day"], bool)
    assert isinstance(data["elimination_applied"], bool)
    assert isinstance(data["benefit_paid_cents"], int)


def assert_partnership_disregard(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["protected_asset_cents"], int)
    assert data["disregard_status"] in ("ACCRUING", "FROZEN")


def assert_trigger_certification(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "BenefitTriggerCertification is append-only and must not expose updated_at")
    assert "version" not in data or data.get("version") is None, (
        "BenefitTriggerCertification is append-only and must not expose version")
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["adl_deficiencies"], list)
    assert isinstance(data["cognitive_impairment"], bool)
    assert data["decision"] in ("CERTIFIED", "NOT_CERTIFIED")


def assert_ledger_entry(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["policy_id"], str)
    assert data["source_kind"] in (
        "CLAIM_PAYMENT", "NONFORFEITURE_REDUCTION", "INFLATION_GROWTH")
    assert isinstance(data["amount_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_pool_invariants(pool: dict):
    """Pool reconciliation invariants that hold after any operation."""
    assert pool["remaining_pool_cents"] >= 0
    assert pool["nonforfeiture_reduction_cents"] >= 0
    # remaining = inflated_pool - lifetime_paid, floored at 0
    expected_remaining = max(0, pool["inflated_pool_cents"] - pool["lifetime_paid_cents"])
    assert pool["remaining_pool_cents"] == expected_remaining, (
        f"remaining_pool_cents should be inflated_pool_cents - lifetime_paid_cents "
        f"floored at 0: expected {expected_remaining}, got {pool['remaining_pool_cents']}")
