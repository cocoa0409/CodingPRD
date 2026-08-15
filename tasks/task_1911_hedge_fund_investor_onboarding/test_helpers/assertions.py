"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict):
    assert isinstance(data, dict), "entity payload must be a dict"
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fund_name"], str) and data["fund_name"]
    assert isinstance(data["domicile"], str) and data["domicile"]
    assert isinstance(data["gate_threshold_pct"], (int, float))
    assert isinstance(data["lockup_months_default"], int)
    assert isinstance(data["notice_days_default"], int)
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert data["suspension_status"] in ("NOT_SUSPENDED", "SUSPENDED")
    assert isinstance(data["total_net_assets_cents"], int)


def assert_share_class(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["class_code"], str) and data["class_code"]
    assert isinstance(data["min_initial_investment_cents"], int)
    assert isinstance(data["min_additional_investment_cents"], int)
    assert isinstance(data["management_fee_bps"], int)
    assert isinstance(data["performance_fee_bps"], int)
    assert isinstance(data["hurdle_rate_bps"], int)
    assert isinstance(data["high_water_mark_required"], bool)
    assert isinstance(data["lockup_months"], int)
    assert isinstance(data["notice_days"], int)
    assert data["redemption_frequency"] in ("MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL")
    assert isinstance(data["is_open_for_subscription"], bool)
    assert isinstance(data["is_open_for_redemption"], bool)


def assert_nav_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert data["status"] in ("OPEN", "NAV_FINALIZED", "CLOSED")
    assert is_iso8601_timestamp(data["period_start_utc"])
    assert is_iso8601_timestamp(data["period_end_utc"])


def assert_series(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["series_index"], int) and data["series_index"] >= 1
    assert data["status"] in ("OPEN", "FINALIZED", "ROLLED")
    assert isinstance(data["equalization_factor_bps"], int)


def assert_investor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["investor_type"] in (
        "INDIVIDUAL", "JOINT", "CORPORATION", "TRUST",
        "PARTNERSHIP", "LLC", "EMPLOYEE_BENEFIT_PLAN",
    )
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["is_us_person"], bool)
    assert data["kyc_status"] in (
        "NOT_STARTED", "DOCUMENTS_PENDING", "UNDER_REVIEW",
        "APPROVED", "REJECTED", "EXPIRED",
    )
    assert data["accreditation_status"] in (
        "UNVERIFIED", "ACCREDITED", "QUALIFIED_PURCHASER", "EXPIRED",
    )
    assert isinstance(data["aggregate_unfunded_commitment_cents"], int)


def assert_kyc_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_sequence"], int) and data["case_sequence"] >= 1
    assert data["risk_rating"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")
    assert isinstance(data["required_documents"], list)
    assert isinstance(data["submitted_documents"], list)
    assert isinstance(data["pep_hit"], bool)
    assert isinstance(data["sanctions_hit"], bool)
    assert isinstance(data["adverse_media_hit"], bool)
    assert data["status"] in (
        "OPEN", "AWAITING_DOCUMENTS", "IN_REVIEW",
        "APPROVED", "REJECTED", "ESCALATED",
    )


def assert_accreditation(data: dict):
    _assert_common_fields(data)
    assert data["attestation_tier"] in ("ACCREDITED", "QUALIFIED_PURCHASER")
    assert data["evidence_type"] in (
        "INCOME_STATEMENT", "NET_WORTH_CERT", "CPA_LETTER",
        "LICENSED_PROFESSIONAL", "ENTITY_ASSETS",
    )
    assert data["status"] in ("PENDING_REVIEW", "VERIFIED", "REJECTED", "EXPIRED")


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["commitment_amount_cents"], int)
    assert isinstance(data["funded_amount_cents"], int)
    assert isinstance(data["late_fees_accrued_cents"], int)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "KYC_HOLD", "COMPLIANCE_APPROVED",
        "FUNDING_PARTIAL", "FUNDED", "ACCEPTED", "REJECTED", "CANCELLED",
    )


def assert_side_letter(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["terms_document_id"], str)
    assert isinstance(data["mfn_election_active"], bool)
    assert isinstance(data["elected_clause_ids"], list)
    assert data["status"] in ("DRAFT", "EXECUTED", "SUPERSEDED", "TERMINATED")


def assert_mfn_clause(data: dict):
    _assert_common_fields(data)
    assert data["clause_tag"] in (
        "FEE_REBATE", "LIQUIDITY", "INFORMATION_RIGHTS",
        "CAPACITY_RIGHTS", "CO_INVEST",
    )
    assert isinstance(data["capacity_threshold_cents"], int)
    assert isinstance(data["fee_rebate_bps"], int)
    assert isinstance(data["notice_days_reduction"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_capital_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["high_water_mark_cents"], int)
    assert isinstance(data["accrued_performance_fee_cents"], int)
    assert isinstance(data["equalization_deposit_cents"], int)
    assert data["status"] in ("ACTIVE", "REDEMPTION_PENDING", "CLOSED")


def assert_series_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cost_basis_cents"], int)
    assert data["status"] in ("OUTSTANDING", "PARTIALLY_REDEEMED", "FULLY_REDEEMED", "ROLLED")


def assert_redemption(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["requested_amount_cents"], int)
    assert data["status"] in (
        "PENDING", "APPROVED", "PARTIALLY_APPROVED", "DEFERRED",
        "SETTLED", "REJECTED", "CANCELLED",
    )
    assert isinstance(data["gate_applied_pct"], (int, float))
    assert isinstance(data["settled_amount_cents"], int)


def assert_statement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["closing_balance_cents"], int)
    assert isinstance(data["contributions_cents"], int)
    assert isinstance(data["distributions_cents"], int)
    assert isinstance(data["management_fee_cents"], int)
    assert isinstance(data["performance_fee_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "DELIVERED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_fund_net_assets_identity(fund: dict, capital_accounts: list):
    """Fund.total_net_assets_cents equals the sum of all current_balance_cents."""
    total = sum(ca.get("current_balance_cents", 0) for ca in capital_accounts)
    assert fund["total_net_assets_cents"] == total, (
        f"Fund total_net_assets_cents {fund['total_net_assets_cents']} != "
        f"sum of capital account balances {total}"
    )
