"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape of one resource type against the
PRD contract (field presence, formats, enum vocabularies).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PROGRAM_YEAR_STATUSES = ["DRAFT", "OPEN", "CLOSED", "REPORTED"]
ALLY_ENROLL_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
STANDING_TIERS = ["PREFERRED", "STANDARD", "PROBATION"]
APPLICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "PRE_INSPECTION",
    "POST_INSPECTION",
    "VERIFIED",
    "APPROVED",
    "PAID",
    "REJECTED",
    "WITHDRAWN",
]
AUTO_FLAG_STATUSES = ["CLEAR", "SUSPECT"]
PACING_TIERS = ["STANDARD_TIER", "MID_TIER", "HIGH_TIER"]
INSPECTION_KINDS = ["PRE", "POST"]
INSPECTION_OUTCOMES = ["PENDING", "PASSED", "FAILED"]
CLAIM_METHODS = ["DEEMED", "MEASURED"]
FRAUD_FLAG_KINDS = ["SAME_SERVICE_ADDRESS", "ALLY_BURST", "INVOICE_GAP_SMALL"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_program_year(data: dict):
    """Validate a ProgramYear response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["program_year_label"], str)
    assert isinstance(data["budget_cap_cents"], int) and data["budget_cap_cents"] > 0
    assert isinstance(data["savings_goal_kwh"], int) and data["savings_goal_kwh"] > 0
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["reported_kwh"], int)
    assert isinstance(data["adjusted_kwh"], int)
    assert isinstance(data["goal_attainment_pct"], int)
    assert data["status"] in PROGRAM_YEAR_STATUSES


def assert_measure(data: dict):
    """Validate a Measure response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_year_id", ""))
    assert isinstance(data["measure_code"], str) and data["measure_code"]
    assert isinstance(data["measure_name"], str)
    assert isinstance(data["base_rate_cents"], int)
    assert isinstance(data["deemed_kwh_per_unit"], int)
    assert isinstance(data["requires_post_inspection"], bool)
    assert isinstance(data["is_active"], bool)


def assert_trade_ally(data: dict):
    """Validate a TradeAlly response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["ally_name"], str) and data["ally_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["performance_score"], int)
    assert data["standing_tier"] in STANDING_TIERS
    assert data["enroll_status"] in ALLY_ENROLL_STATUSES


def assert_application(data: dict):
    """Validate a RebateApplication response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_year_id", ""))
    assert is_valid_uuid(data.get("trade_ally_id", ""))
    assert isinstance(data["customer_account_number"], str)
    assert isinstance(data["service_address"], str)
    assert isinstance(data["invoice_number"], str)
    assert isinstance(data["invoice_date"], str)
    assert isinstance(data["incentive_total_cents"], int)
    assert isinstance(data["claimed_kwh"], int)
    assert isinstance(data["final_kwh"], int)
    assert isinstance(data["inspection_required"], bool)
    assert isinstance(data["risk_score"], int)
    assert data["auto_flag_status"] in AUTO_FLAG_STATUSES
    assert data["status"] in APPLICATION_STATUSES


def assert_line_item(data: dict):
    """Validate an ApplicationLineItem response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("measure_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0


def assert_savings_claim(data: dict):
    """Validate a SavingsClaim response: id + created_at only, no version."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("line_item_id", ""))
    assert data["claim_method"] in CLAIM_METHODS


def assert_inspection(data: dict):
    """Validate an Inspection response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["inspection_kind"] in INSPECTION_KINDS
    assert isinstance(data["scheduled_on"], str)
    assert data["outcome"] in INSPECTION_OUTCOMES


def assert_evaluation_adjustment(data: dict):
    """Validate an EvaluationAdjustment response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_year_id", ""))
    assert isinstance(data["realization_rate_pct"], int)
    assert 0 <= data["realization_rate_pct"] <= 100
    assert isinstance(data["effective_on"], str)


def assert_fraud_flag(data: dict):
    """Validate a FraudFlag response: id + created_at only, no version."""
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["flag_kind"] in FRAUD_FLAG_KINDS
    assert isinstance(data["weight"], int)


def assert_program_ledger_invariants(data: dict):
    """Domain invariants that must hold on a program year after any operation."""
    assert data["committed_cents"] >= 0, "committed_cents must never go negative"
    assert data["paid_cents"] >= 0, "paid_cents must never go negative"
    assert data["reported_kwh"] >= 0, "reported_kwh must never go negative"
    assert data["adjusted_kwh"] >= 0, "adjusted_kwh must never go negative"
    assert data["committed_cents"] <= data["budget_cap_cents"], (
        "committed_cents must never exceed the budget cap"
    )
