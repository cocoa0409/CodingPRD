"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


CASE_STATUSES = [
    "INTAKE", "CENSUS_PENDING", "CENSUS_RECEIVED", "CLAIMS_PENDING",
    "RATING_IN_PROGRESS", "QUOTED", "NEGOTIATING", "APPROVED", "DECLINED",
    "WITHDRAWN",
]
BROKER_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
CENSUS_STATUSES = ["PENDING", "VALIDATED", "REJECTED"]
CLAIMS_STATUSES = ["PENDING", "SUBMITTED", "REVIEWED", "REJECTED"]
PLAN_STATUSES = ["DRAFT", "MODELED", "SELECTED", "REJECTED"]
QUOTE_STATUSES = [
    "DRAFT", "PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED", "EXPIRED",
    "SUPERSEDED",
]
STOP_LOSS_STATUSES = ["DRAFT", "QUOTED", "BOUND", "DECLINED"]
ROUND_STATUSES = ["PROPOSED", "ACCEPTED", "REJECTED", "WITHDRAWN"]
ENROLLMENT_EVENT_STATUSES = ["REPORTED", "PROCESSED", "VOIDED_GUARANTEE"]
DISCLOSURE_STATUSES = ["PENDING", "DISCLOSED", "ACKNOWLEDGED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_underwriting_case(data: dict):
    _assert_common(data)
    assert isinstance(data["group_name"], str) and data["group_name"]
    assert isinstance(data["group_size"], int)
    assert isinstance(data["sic_code"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["current_premium_annual"], int)
    assert data["funding_type"] in ["FULLY_INSURED", "LEVEL_FUNDED", "SELF_FUNDED"]
    assert data["status"] in CASE_STATUSES
    assert isinstance(data["assigned_underwriter_id"], str)
    assert isinstance(data["broker_id"], str)


def assert_broker(data: dict):
    _assert_common(data)
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert isinstance(data["license_number"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["commission_pct"], (int, float))
    assert data["status"] in BROKER_STATUSES


def assert_census_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["total_employees"], int)
    assert isinstance(data["enrolled_employees"], int)
    assert isinstance(data["dependent_count"], int)
    assert isinstance(data["tier_distribution"], dict)
    assert data["status"] in CENSUS_STATUSES


def assert_claims_experience(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["total_paid_claims_cents"], int)
    assert isinstance(data["total_enrollment_months"], int)
    assert isinstance(data["pooling_threshold_cents"], int)
    assert data["status"] in CLAIMS_STATUSES


def assert_plan_design(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["plan_name"], str)
    assert isinstance(data["deductible_individual"], int)
    assert isinstance(data["oop_max_individual"], int)
    assert isinstance(data["coinsurance_pct"], (int, float))
    assert data["status"] in PLAN_STATUSES


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["plan_design_id"], str)
    assert isinstance(data["quote_number"], int)
    assert data["funding_type"] in ["FULLY_INSURED", "LEVEL_FUNDED"]
    assert data["status"] in QUOTE_STATUSES
    assert isinstance(data["negotiation_round"], int)


def assert_stop_loss_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["specific_deductible_cents"], int)
    assert isinstance(data["aggregate_attachment_pct"], (int, float))
    assert data["status"] in STOP_LOSS_STATUSES


def assert_negotiation_round(data: dict):
    _assert_common(data)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["round_number"], int)
    assert data["proposed_by"] in ["UNDERWRITER", "BROKER"]
    assert data["status"] in ROUND_STATUSES


def assert_enrollment_change_event(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["quote_id"], str)
    assert data["event_type"] in [
        "NEW_HIRE", "TERMINATION", "COBRA_ELECTION", "PLAN_MIGRATION",
    ]
    assert isinstance(data["change_count"], int)
    assert data["status"] in ENROLLMENT_EVENT_STATUSES


def assert_commission_disclosure(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["quote_id"], str)
    assert isinstance(data["broker_id"], str)
    assert data["status"] in DISCLOSURE_STATUSES


def assert_level_funded_split_invariants(quote: dict):
    """For a LEVEL_FUNDED quote the three PEPM components sum exactly to the PEPM rate."""
    if quote.get("funding_type") == "LEVEL_FUNDED":
        total = (
            quote["claims_fund_cents"]
            + quote["admin_fee_cents"]
            + quote["stop_loss_premium_cents"]
        )
        assert total == quote["pepm_rate_cents"], (
            f"Level-funded components {total} must equal pepm_rate_cents "
            f"{quote['pepm_rate_cents']}"
        )
