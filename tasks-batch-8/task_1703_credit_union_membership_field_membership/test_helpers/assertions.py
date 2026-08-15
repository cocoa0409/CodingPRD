"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_fields(data: dict):
    """Immutable ledger rows carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger rows must not expose updated_at"
    assert "version" not in data, "ledger rows must not expose version"


def assert_charter(data: dict):
    _assert_common_fields(data)
    assert data["bond_type"] in (
        "SINGLE_OCCUPATIONAL", "COMMUNITY", "ASSOCIATIONAL",
        "MULTIPLE_COMMON_BOND")
    assert isinstance(data["par_value_cents"], int)
    assert data["par_value_cents"] > 0
    assert data["status"] == "ACTIVE"


def assert_segment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("charter_id", ""))
    assert data["segment_type"] in ("OCCUPATIONAL", "COMMUNITY", "ASSOCIATIONAL")
    assert isinstance(data["descriptor"], str) and len(data["descriptor"]) > 0
    assert isinstance(data["required_documents"], list)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_amendment_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("charter_id", ""))
    assert data["amendment_type"] in ("ADD_SEGMENT", "RETIRE_SEGMENT")
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["baseline_charter_version"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "EFFECTIVE")
    assert isinstance(data["submitted_by_user_id"], str)


def assert_membership_application(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicant_full_name"], str)
    assert data["basis"] in ("SEGMENT_MATCH", "FAMILY", "HOUSEHOLD")
    assert isinstance(data["documents_provided"], list)
    assert isinstance(data["required_documents"], list)
    assert isinstance(data["docs_complete"], bool)
    assert isinstance(data["requested_document_codes"], list)
    assert data["status"] in (
        "UNDER_REVIEW", "DOCS_REQUESTED", "APPROVED", "DENIED")
    assert isinstance(data["filed_by_user_id"], str)


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert data["eligibility_basis"] in ("SEGMENT_MATCH", "FAMILY", "HOUSEHOLD")
    assert isinstance(data["membership_effective_date"], str)
    assert data["status"] in (
        "ACTIVE", "INELIGIBLE_UNDER_REVIEW", "GRACE_PERIOD", "CLOSED_INELIGIBLE")
    assert data["tier"] in ("STANDARD", "SELECT", "PREMIER")
    assert isinstance(data["tenure_months"], int)
    assert isinstance(data["qualifying_balance_cents"], int)


def assert_share_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["account_type"] in ("PRIMARY", "SUPPLEMENTAL")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["opened_date"], str)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_share_transaction(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("share_account_id", ""))
    assert data["kind"] in (
        "DEPOSIT", "WITHDRAWAL", "DIVIDEND_CREDIT", "CLOSURE_DISBURSEMENT")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0
    assert isinstance(data["posted_date"], str)
    assert isinstance(data["running_balance_cents"], int)
    assert data["origin"] in ("MANUAL", "SYSTEM")


def assert_product_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["product_code"] in (
        "MONEY_MARKET", "SHARE_CERTIFICATE", "PREMIER_LOAN")
    assert is_valid_uuid(data.get("funding_share_account_id", ""))
    assert data["required_tier"] in ("STANDARD", "SELECT", "PREMIER")
    assert data["tier_at_enrollment"] in ("STANDARD", "SELECT", "PREMIER")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_dividend_declaration(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["rate_bps"], int)
    assert data["method"] in ("AVERAGE_DAILY_BALANCE", "MINIMUM_DAILY_BALANCE")
    assert isinstance(data["payable_date"], str)
    assert data["status"] in ("DECLARED", "PAID", "VOIDED")
    assert isinstance(data["declared_pool_cents"], int)
    assert isinstance(data["declared_by_user_id"], str)


def assert_dividend_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("declaration_id", ""))
    assert is_valid_uuid(data.get("share_account_id", ""))
    assert isinstance(data["accrued_amount_cents"], int)
    assert isinstance(data["tier_bonus_bps_applied"], int)
    assert data["status"] in ("ACCRUED", "CREDITED", "VOIDED")


def assert_annual_meeting(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["meeting_date"], str)
    assert isinstance(data["record_date"], str)
    assert isinstance(data["voting_open_date"], str)
    assert isinstance(data["quorum_threshold"], int)
    assert data["quorum_threshold"] > 0
    assert data["status"] in ("SCHEDULED", "HELD", "ADJOURNED_NO_QUORUM")


def assert_ballot(data: dict):
    _assert_ledger_fields(data)
    assert is_valid_uuid(data.get("meeting_id", ""))
    assert isinstance(data.get("member_id"), str) and len(data["member_id"]) > 0
    assert data["choice"] in ("FOR_SLATE_A", "FOR_SLATE_B", "ABSTAIN")
    assert isinstance(data["cast_date"], str)


def assert_eligibility_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["reason"] in ("MANUAL_FLAG", "SEGMENT_RETIRED")
    assert data["status"] in ("OPEN", "CURED", "CONFIRMED_INELIGIBLE")
    assert isinstance(data["flagged_by_user_id"], str)
