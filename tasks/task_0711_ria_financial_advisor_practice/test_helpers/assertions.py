"""Entity assertions and domain invariant checkers for the RIA Practice API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Common fields every entity carries (PRD §2.4): id, created_at,
    updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["billing_method"] in ("ARREARS", "ADVANCE")
    assert data["status"] in ("ACTIVE", "CLOSED")
    for f in ("billable_aum_cents", "aggregated_aum_cents", "breakpoint_tier_index"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} must be non-negative"
    # billable AUM can never exceed aggregated AUM (billable is a subset) (PRD §2.8).
    assert data["billable_aum_cents"] <= data["aggregated_aum_cents"], \
        "billable_aum_cents must not exceed aggregated_aum_cents"


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert isinstance(data["is_locked"], bool)
    assert data["minimum_annual_fee_cents"] >= 0


def assert_client(data: dict):
    _assert_common(data)
    assert data["onboarding_status"] in (
        "PROSPECT", "KYC_VERIFIED", "IPS_SIGNED", "ACTIVE", "DISENGAGED")
    assert data["suitability_band"] in ("CONSERVATIVE", "MODERATE", "AGGRESSIVE")
    assert 0 <= data["risk_capacity_score"] <= 100
    assert 0 <= data["risk_tolerance_score"] <= 100


def assert_ips(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PROPOSED", "APPROVED", "SUPERSEDED")
    assert 0 <= data["max_equity_pct"] <= 100
    assert data["drift_tolerance_bps"] > 0
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_portfolio(data: dict):
    _assert_common(data)
    assert 0 <= data["model_equity_pct"] <= 100
    assert isinstance(data["is_published"], bool)
    assert isinstance(data["target_weights"], list)


def assert_account(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "FROZEN", "CLOSED")
    assert data["account_type"] in (
        "TAXABLE", "IRA", "ROTH", "TRUST", "HELD_AWAY_401K")
    assert isinstance(data["held_away"], bool)
    assert isinstance(data["billable"], bool)
    assert data["market_value_cents"] >= 0
    assert 0 <= data["equity_value_cents"] <= data["market_value_cents"], \
        "equity_value_cents must be within [0, market_value_cents]"
    assert isinstance(data["drift_bps"], int) and data["drift_bps"] >= 0
    assert isinstance(data["rebalance_flagged"], bool)


def assert_fee_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "CALCULATED", "FINALIZED", "VOIDED")
    assert data["billing_method_snapshot"] in ("ARREARS", "ADVANCE")
    for f in ("basis_aum_cents", "gross_fee_cents", "assessed_fee_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer (cents)"
        assert data[f] >= 0, f"{f} must be non-negative"


def assert_financial_plan(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in ("DRAFT", "ACTIVE", "ARCHIVED")
    assert data["review_status"] in ("NEEDS_REVIEW", "REVIEWED", "STALE")
    assert data["assumed_annual_return_bps"] >= 0
    assert data["monthly_contribution_cents"] >= 0


def assert_goal(data: dict):
    _assert_common(data)
    assert data["target_amount_cents"] > 0
    assert data["current_amount_cents"] >= 0
    assert isinstance(data["funded_ratio_bps"], int) and data["funded_ratio_bps"] >= 0
    assert isinstance(data["on_track"], bool)
    assert data["priority"] in ("ESSENTIAL", "SECONDARY", "ASPIRATIONAL")


def assert_rebalance_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "APPROVED", "EXECUTED", "REJECTED")
    assert isinstance(data["trade_equity_delta_cents"], int)


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED")
    assert data["cadence_days"] > 0
    assert isinstance(data["is_overdue"], bool)


def assert_compliance_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "REMEDIATION", "SATISFIED", "ARCHIVED")
    assert data["subject_type"] in ("CLIENT", "ACCOUNT", "HOUSEHOLD")
    assert data["obligation_type"] in (
        "REG_BI_DISCLOSURE", "FORM_ADV_DELIVERY", "IPS_ARCHIVE", "FEE_DISCLOSURE")
    assert isinstance(data["remediation_round"], int) and data["remediation_round"] >= 0
