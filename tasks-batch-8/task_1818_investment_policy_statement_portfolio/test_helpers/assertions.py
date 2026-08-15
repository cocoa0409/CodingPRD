"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §2.9)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into an aware datetime."""
    assert isinstance(s, str), f"expected an ISO 8601 string, got {s!r}"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_iso_instant_equal(actual, expected, msg=None):
    """Assert two ISO 8601 timestamps denote the same UTC instant.

    PRD pins the instant carried by clock-derived fields (§2.5: activated_at,
    generated_at, expires_at, ... "read this clock"; §3.2: next_review_due is
    computed from activated_at), but the three-fractional-digit serialization
    of §2.2/§2.4 is stated only for api_request_timestamp and
    created_at/updated_at — so comparisons here are on the instant, not the
    string rendering.
    """
    a = _parse_instant(actual)
    e = _parse_instant(expected)
    assert a == e, msg or f"instant mismatch: {actual!r} != {expected!r}"


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version is a positive integer"


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["risk_tolerance_score"], int)
    assert 1 <= data["risk_tolerance_score"] <= 100
    assert data["status"] in ["PROSPECT", "ACTIVE", "TERMINATED"]
    assert isinstance(data["total_aum_cents"], int)


def assert_benchmark(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["description"], str)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_ips(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["benchmark_id"])
    assert isinstance(data["objective_text"], str)
    assert 1 <= data["risk_tolerance_score"] <= 100
    assert 1 <= data["review_cadence_months"] <= 24
    assert data["status"] in ["DRAFT", "PENDING_COMPLIANCE", "PENDING_CLIENT",
                              "ACTIVE", "SUPERSEDED", "ARCHIVED"]
    assert isinstance(data["review_overdue"], bool)


def assert_allocation_target(data: dict):
    _assert_common_fields(data)
    assert data["asset_class"] in ["US_EQUITY", "INTL_EQUITY", "FIXED_INCOME",
                                   "CASH_EQUIVALENT", "ALTERNATIVES"]
    assert 0 < float(data["target_pct"]) <= 100
    assert 0 < float(data["band_pct"]) <= 50


def assert_portfolio(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["client_id"])
    assert data["tax_status"] in ["TAXABLE", "TAX_DEFERRED", "TAX_EXEMPT"]
    assert data["lifecycle_status"] in ["OPEN", "ACTIVE", "FROZEN", "CLOSED"]
    assert data["drift_status"] in ["WITHIN_BANDS", "BREACHED", "UNTRACKED"]
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["total_value_cents"], int)
    assert isinstance(data["lifetime_realized_gains_cents"], int)


def assert_security(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert data["asset_class"] in ["US_EQUITY", "INTL_EQUITY", "FIXED_INCOME",
                                   "CASH_EQUIVALENT", "ALTERNATIVES"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 1
    assert data["trading_status"] in ["LISTED", "HALTED", "DELISTED"]


def assert_position(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["portfolio_id"])
    assert is_valid_uuid(data["security_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert isinstance(data["cost_basis_cents"], int) and data["cost_basis_cents"] >= 0
    assert isinstance(data["market_value_cents"], int)
    assert isinstance(data["unrealized_gain_cents"], int)


def assert_cash_flow_event(data: dict):
    """Append-only ledger entry: id + created_at only from the standard set
    (PRD §2.4) — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CashFlowEvent has no updated_at (PRD §2.4)"
    assert "version" not in data, "CashFlowEvent has no version (PRD §2.4)"
    assert is_valid_uuid(data["portfolio_id"])
    assert is_iso8601_timestamp(data["occurred_at"])
    assert data["kind"] in ["MANUAL_DEPOSIT", "MANUAL_WITHDRAWAL", "TRADE_EXECUTION",
                            "TRADE_VOID", "WITHDRAWAL_DISBURSEMENT", "SETTLEMENT_PROCEEDS"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
    assert isinstance(data["valuation_before_cents"], int)
    assert data["source_type"] in ["MANUAL", "TRADE", "WITHDRAWAL"]


def assert_restricted_list_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["security_id"])
    assert data["restriction_level"] in ["NO_BUY", "NO_TRADE"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert data["status"] in ["SCHEDULED", "ACTIVE", "EXPIRED"]


def assert_rebalance_proposal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["portfolio_id"])
    assert data["trigger_type"] in ["DRIFT_BREACH", "CASH_FLOW", "MANUAL"]
    assert data["status"] in ["PROPOSED", "NEEDS_REVISION", "APPROVED", "EXECUTED",
                              "REJECTED", "CANCELLED", "EXPIRED"]
    assert isinstance(data["total_buys_cents"], int)
    assert isinstance(data["total_sells_cents"], int)
    assert isinstance(data["est_tax_reserve_cents"], int)
    assert isinstance(data["cash_delta_cents"], int)


def assert_trade_instruction(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proposal_id"])
    assert is_valid_uuid(data["security_id"])
    assert data["side"] in ["BUY", "SELL"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["pinned_price_cents"], int) and data["pinned_price_cents"] >= 1
    assert isinstance(data["est_proceeds_cents"], int)
    assert isinstance(data["est_tax_impact_cents"], int)
    assert data["status"] in ["PENDING", "BLOCKED", "EXECUTED", "VOIDED", "CANCELLED"]


def assert_withdrawal_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["portfolio_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["funding_mode"] in ["CASH_FIRST", "PRO_RATA", "TAX_AWARE"]
    assert data["status"] in ["SUBMITTED", "MODELED", "APPROVED", "SETTLED",
                              "REJECTED", "CANCELLED"]


def assert_performance_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["portfolio_id"])
    assert is_valid_uuid(data["benchmark_id"])
    assert data["calculation_method"] in ["TIME_WEIGHTED", "MONEY_WEIGHTED"]
    assert data["status"] in ["DRAFT", "FINALIZED"]


def assert_ips_amendment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["ips_id"])
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "QUORUM_REACHED", "APPROVED",
                              "REJECTED", "WITHDRAWN"]
    assert isinstance(data["approve_votes"], int)
    assert isinstance(data["reject_votes"], int)


def assert_committee_minute(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amendment_refs"], list)
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert data["status"] in ["DRAFT", "RATIFIED"]


def assert_portfolio_valuation_invariants(portfolio: dict, positions: list):
    """PRD §2.9: total_value_cents == cash + SUM(position market values)."""
    mv_sum = sum(p["market_value_cents"] for p in positions)
    assert portfolio["total_value_cents"] == portfolio["cash_balance_cents"] + mv_sum, (
        f"total {portfolio['total_value_cents']} != cash "
        f"{portfolio['cash_balance_cents']} + positions {mv_sum}"
    )
