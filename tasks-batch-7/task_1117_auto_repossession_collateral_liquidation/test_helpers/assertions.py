"""Entity assertions and domain invariant checkers.

Each assert_* validates the standard system-managed fields (PRD §2.4) plus
the entity's documented fields and enum memberships. The append-only ledger
entry checker asserts the ABSENCE of updated_at/version per PRD §2.4.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ComplaintStatus,
    ConditionGrade,
    ConsignmentStatus,
    CureNoticeStatus,
    DeficiencyNoticeStatus,
    LedgerEntryKind,
    LoanAccountStatus,
    PersonalPropertyItemStatus,
    QuoteType,
    RecoveryCaseStatus,
    RedemptionQuoteStatus,
    RepoAgentStatus,
    RepoAssignmentStatus,
    SaleRecordStatus,
)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant. PRD pins the instant, not the exact
    string rendering, so tests compare parsed datetimes."""
    assert isinstance(value, str) and value, f"expected non-empty ISO timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_borrower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["email"], str) and data["email"]


def assert_loan_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("borrower_id", "")), "borrower_id must be a valid UUID"
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["governing_state_code"], str)
    for field in ("principal_balance_cents", "apr_bps", "monthly_payment_cents",
                  "missed_installments", "accrued_interest_cents", "late_fees_cents",
                  "paid_to_date_cents", "total_outstanding_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["status"] in [s.value for s in LoanAccountStatus]


def assert_recovery_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("loan_account_id", "")), "loan_account_id must be a valid UUID"
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]
    assert data["status"] in [s.value for s in RecoveryCaseStatus]
    assert isinstance(data.get("property_item_count", 0), int)


def assert_cure_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert data["status"] in [s.value for s in CureNoticeStatus]
    assert isinstance(data["cure_amount_cents"], int)
    assert is_iso8601_timestamp(data.get("sent_at", "")), "sent_at must be ISO 8601"


def assert_repo_agent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["licensed_state_codes"], list)
    assert isinstance(data["max_active_assignments"], int)
    assert data["status"] in [s.value for s in RepoAgentStatus]
    assert isinstance(data["performance_score_lifetime"], int)
    assert isinstance(data["performance_score_rolling"], int)


def assert_repo_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a valid UUID"
    assert data["status"] in [s.value for s in RepoAssignmentStatus]
    assert is_iso8601_timestamp(data.get("field_window_start", ""))
    assert is_iso8601_timestamp(data.get("field_window_end", ""))


def assert_property_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["estimated_value_cents"], int)
    assert data["status"] in [s.value for s in PersonalPropertyItemStatus]


def assert_redemption_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert data["quote_type"] in [s.value for s in QuoteType]
    assert data["status"] in [s.value for s in RedemptionQuoteStatus]
    assert isinstance(data["quoted_amount_cents"], int)
    assert isinstance(data["per_diem_cents"], int)
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"


def assert_auction_house(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fee_bps"], int)
    assert isinstance(data["transport_fee_cents"], int)


def assert_consignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert is_valid_uuid(data.get("auction_house_id", "")), "auction_house_id must be a valid UUID"
    assert data["status"] in [s.value for s in ConsignmentStatus]
    assert isinstance(data["reserve_price_cents"], int)
    assert isinstance(data["relist_count"], int)


def assert_sale_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("consignment_id", "")), "consignment_id must be a valid UUID"
    assert isinstance(data["gross_sale_cents"], int)
    assert isinstance(data["auction_fee_cents"], int)
    assert isinstance(data["transport_fee_cents"], int)
    assert isinstance(data["net_proceeds_cents"], int)
    assert data["status"] in [s.value for s in SaleRecordStatus]


def assert_deficiency_notice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert data["status"] in [s.value for s in DeficiencyNoticeStatus]
    assert isinstance(data["deficiency_amount_cents"], int)
    assert isinstance(data["surplus_cents"], int)
    assert isinstance(data["paid_cents"], int)


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("recovery_case_id", "")), "recovery_case_id must be a valid UUID"
    assert is_valid_uuid(data.get("borrower_id", "")), "borrower_id must be a valid UUID"
    assert data["status"] in [s.value for s in ComplaintStatus]


def assert_ledger_entry(data: dict):
    """Append-only ledger row (PRD §2.4): id + created_at, and updated_at /
    version MUST be absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "ledger entries must not carry version (PRD §2.4)"
    assert data["kind"] in [k.value for k in LedgerEntryKind]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_case_money_invariants(case: dict, loan: dict):
    """Cross-resource invariants that hold at every observable point."""
    assert loan["paid_to_date_cents"] >= 0, "paid_to_date_cents never goes negative"
    assert case["property_item_count"] >= 0
