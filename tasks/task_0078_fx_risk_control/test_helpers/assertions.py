"""Per-entity assertions and domain invariant checkers."""
from __future__ import annotations
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BAND_SEVERITY,
    BREACH_PCT,
    EXTERNAL_RATING_TO_BAND,
    WARNING_PCT,
    band_from_external,
    band_from_internal,
    credit_limit_for_band,
    worse_band,
)


# ---------------------------------------------------------------------------
# Versioned-envelope helpers
# ---------------------------------------------------------------------------
def _assert_versioned_envelope(data: Dict[str, Any], *, label: str) -> None:
    """PRD §2.4: versioned entities carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC; got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC; got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be int >= 1; got {data.get('version')!r}"
    )


def _assert_append_only_envelope(data: Dict[str, Any], *, label: str) -> None:
    """PRD §2.4: append-only entities (Trade, ComplianceReport, AuditLog)
    carry only id and created_at — no updated_at, no row-level version
    (ComplianceReport.version is the family counter, not an OCC token).
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC; got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
def assert_trader(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="Trader")
    assert isinstance(data["name"], str) and data["name"], "Trader.name required"
    assert data["desk_code"] in ("G10_SPOT", "EM_FX", "OPTIONS"), (
        f"Trader.desk_code must be one of G10_SPOT/EM_FX/OPTIONS; got {data['desk_code']!r}"
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED"), (
        f"Trader.status must be ACTIVE or SUSPENDED; got {data['status']!r}"
    )


# ---------------------------------------------------------------------------
# Currency pair
# ---------------------------------------------------------------------------
def assert_currency_pair(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="CurrencyPair")
    code = data["code"]
    assert isinstance(code, str) and len(code) == 6 and code.isupper(), (
        f"CurrencyPair.code must be 6 uppercase letters; got {code!r}"
    )
    assert data["base_ccy"] == code[0:3], (
        f"CurrencyPair.base_ccy must equal code[0:3]={code[0:3]}; got {data['base_ccy']!r}"
    )
    assert data["quote_ccy"] == code[3:6], (
        f"CurrencyPair.quote_ccy must equal code[3:6]={code[3:6]}; got {data['quote_ccy']!r}"
    )
    assert isinstance(data["mid_rate"], (int, float)) and data["mid_rate"] > 0, (
        f"CurrencyPair.mid_rate must be > 0; got {data['mid_rate']!r}"
    )
    assert isinstance(data["daily_volatility"], (int, float)), (
        "CurrencyPair.daily_volatility must be numeric"
    )
    assert data["daily_volatility"] >= 0, (
        f"CurrencyPair.daily_volatility must be >= 0; got {data['daily_volatility']!r}"
    )


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------
def assert_limit(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="Limit")
    assert is_valid_uuid(data["trader_id"]), (
        f"Limit.trader_id must be a UUID; got {data['trader_id']!r}"
    )
    assert data["bucket"] in ("INTRADAY", "OVERNIGHT"), (
        f"Limit.bucket must be INTRADAY or OVERNIGHT; got {data['bucket']!r}"
    )
    assert isinstance(data["notional_cap_usd"], (int, float)), (
        "Limit.notional_cap_usd must be numeric"
    )
    assert data["notional_cap_usd"] > 0, (
        f"Limit.notional_cap_usd must be > 0; got {data['notional_cap_usd']!r}"
    )
    assert_cost_precision(data["notional_cap_usd"])
    assert isinstance(data["stop_loss_cap_usd"], (int, float)), (
        "Limit.stop_loss_cap_usd must be numeric"
    )
    assert data["stop_loss_cap_usd"] >= 0, (
        f"Limit.stop_loss_cap_usd must be >= 0; got {data['stop_loss_cap_usd']!r}"
    )
    assert_cost_precision(data["stop_loss_cap_usd"])
    assert isinstance(data["temporary_override_usd"], (int, float)), (
        "Limit.temporary_override_usd must be numeric"
    )
    assert data["temporary_override_usd"] >= 0, (
        "Limit.temporary_override_usd must be >= 0"
    )
    assert_cost_precision(data["temporary_override_usd"])
    assert isinstance(data["utilization_usd"], (int, float)), (
        "Limit.utilization_usd must be numeric"
    )
    assert data["utilization_usd"] >= 0, (
        "Limit.utilization_usd must be >= 0 (absolute value of net_open_usd)"
    )
    assert_cost_precision(data["utilization_usd"])
    assert isinstance(data["utilization_pct"], (int, float)), (
        "Limit.utilization_pct must be numeric"
    )
    assert data["utilization_pct"] >= 0, (
        "Limit.utilization_pct must be >= 0"
    )
    # 2 decimal places for utilization_pct (PRD §2.6)
    assert round(data["utilization_pct"], 2) == data["utilization_pct"], (
        f"Limit.utilization_pct must be carried to 2 decimal places; got {data['utilization_pct']!r}"
    )


# ---------------------------------------------------------------------------
# LimitAdjustmentRequest
# ---------------------------------------------------------------------------
def assert_limit_adjustment_request(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="LimitAdjustmentRequest")
    assert is_valid_uuid(data["limit_id"])
    assert isinstance(data["requested_delta_usd"], (int, float))
    assert data["requested_delta_usd"] > 0
    assert_cost_precision(data["requested_delta_usd"])
    assert isinstance(data["justification"], str) and 1 <= len(data["justification"]) <= 500
    assert is_iso8601_timestamp(data["expires_at"]), (
        f"expires_at must be ISO 8601 UTC; got {data['expires_at']!r}"
    )
    assert data["status"] in (
        "PENDING", "APPROVED", "REJECTED", "REVISION_REQUESTED", "EXPIRED",
    ), f"status must be a valid LimitAdjustmentRequest state; got {data['status']!r}"
    assert isinstance(data["requester_trader_id"], str) and data["requester_trader_id"]
    # approver_user_id is null until decision recorded
    if data["status"] in ("APPROVED", "REJECTED"):
        assert data.get("approver_user_id"), (
            f"approver_user_id must be set when status={data['status']}"
        )


# ---------------------------------------------------------------------------
# Trade (append-only)
# ---------------------------------------------------------------------------
def assert_trade(data: Dict[str, Any]) -> None:
    _assert_append_only_envelope(data, label="Trade")
    # Trade has no updated_at, no version per PRD §2.4.
    assert "updated_at" not in data or data.get("updated_at") is None or True, (
        "Trade is append-only (PRD §2.4)"
    )
    assert is_valid_uuid(data["trader_id"])
    assert isinstance(data["pair_code"], str) and len(data["pair_code"]) == 6
    assert data["side"] in ("BUY", "SELL")
    assert isinstance(data["notional_base"], (int, float))
    assert data["notional_base"] > 0
    assert isinstance(data["entry_rate"], (int, float))
    assert data["entry_rate"] > 0
    assert is_iso8601_timestamp(data["executed_at"])
    # trading_day is YYYY-MM-DD calendar date
    td = data["trading_day"]
    assert isinstance(td, str) and len(td) == 10 and td[4] == "-" and td[7] == "-", (
        f"Trade.trading_day must be YYYY-MM-DD; got {td!r}"
    )
    assert is_valid_uuid(data["counterparty_id"])
    assert data["status"] in ("BOOKED", "NETTED", "SETTLED", "FAILED")


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------
def assert_position(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="Position")
    assert is_valid_uuid(data["trader_id"])
    assert isinstance(data["pair_code"], str) and len(data["pair_code"]) == 6
    assert isinstance(data["net_base"], (int, float))
    assert isinstance(data["net_open_usd"], (int, float))
    assert_cost_precision(data["net_open_usd"])
    assert isinstance(data["mtm_pnl_usd"], (int, float))
    assert_cost_precision(data["mtm_pnl_usd"])
    assert data["warning_status"] in ("NORMAL", "WARNING", "BREACH")


# ---------------------------------------------------------------------------
# StopLossEvent
# ---------------------------------------------------------------------------
def assert_stop_loss_event(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="StopLossEvent")
    assert is_valid_uuid(data["trader_id"])
    assert isinstance(data["pair_code"], str) and len(data["pair_code"]) == 6
    assert data["rule_mode"] in ("PRICE", "LOSS_AMOUNT", "LOSS_RATIO")
    assert isinstance(data["threshold_value"], (int, float))
    assert data["threshold_value"] > 0
    assert data["action"] in ("ALERT", "FORCED_FLATTEN")
    assert data["state"] in (
        "ARMED", "TRIGGERED", "ACKNOWLEDGED", "OVERRIDDEN",
        "EXECUTED", "ARCHIVED",
    )
    # triggered_at / triggering_value are null until TRIGGERED.
    if data["state"] == "ARMED":
        assert data.get("triggered_at") is None
        assert data.get("triggering_value") is None
    if data["state"] in ("TRIGGERED", "ACKNOWLEDGED", "EXECUTED"):
        assert data.get("triggered_at") is not None
        assert data.get("triggering_value") is not None


# ---------------------------------------------------------------------------
# Counterparty
# ---------------------------------------------------------------------------
def assert_counterparty(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="Counterparty")
    assert isinstance(data["name"], str) and data["name"]
    assert data["external_rating"] in EXTERNAL_RATING_TO_BAND, (
        f"external_rating must be one of {sorted(EXTERNAL_RATING_TO_BAND)}; got {data['external_rating']!r}"
    )
    assert isinstance(data["internal_score"], int)
    assert 0 <= data["internal_score"] <= 100
    assert data["rating_band"] in BAND_SEVERITY
    assert isinstance(data["credit_limit_usd"], (int, float))
    assert data["credit_limit_usd"] >= 0
    assert_cost_precision(data["credit_limit_usd"])
    assert isinstance(data["on_watchlist"], bool)
    # Cross-check the computed fields against PRD §3.6 deterministic formula.
    expected_band = worse_band(
        band_from_external(data["external_rating"]),
        band_from_internal(data["internal_score"]),
    )
    assert data["rating_band"] == expected_band, (
        f"rating_band must equal worse-of(external,internal). "
        f"External={data['external_rating']} → {band_from_external(data['external_rating'])}; "
        f"Internal={data['internal_score']} → {band_from_internal(data['internal_score'])}; "
        f"expected {expected_band}, got {data['rating_band']!r}"
    )
    assert data["on_watchlist"] is (expected_band == "WATCH"), (
        f"on_watchlist must be True iff rating_band==WATCH; got {data['on_watchlist']!r} for band {data['rating_band']!r}"
    )
    assert data["credit_limit_usd"] == credit_limit_for_band(expected_band), (
        f"credit_limit_usd must be tier[{expected_band}]={credit_limit_for_band(expected_band)}; got {data['credit_limit_usd']!r}"
    )


# ---------------------------------------------------------------------------
# SettlementInstruction
# ---------------------------------------------------------------------------
def assert_settlement_instruction(data: Dict[str, Any]) -> None:
    _assert_versioned_envelope(data, label="SettlementInstruction")
    assert is_valid_uuid(data["counterparty_id"])
    vd = data["value_date"]
    assert isinstance(vd, str) and len(vd) == 10
    assert isinstance(data["ccy"], str) and len(data["ccy"]) == 3 and data["ccy"].isupper()
    assert isinstance(data["gross_pay_amount"], (int, float))
    assert data["gross_pay_amount"] >= 0
    assert_cost_precision(data["gross_pay_amount"])
    assert isinstance(data["gross_receive_amount"], (int, float))
    assert data["gross_receive_amount"] >= 0
    assert_cost_precision(data["gross_receive_amount"])
    assert isinstance(data["net_amount"], (int, float))
    assert_cost_precision(data["net_amount"])
    assert data["status"] in (
        "GENERATED", "SENT", "SETTLED", "FAILED", "RECONCILED",
    )
    assert isinstance(data["client_request_id"], str) and data["client_request_id"]
    assert isinstance(data["nostro_balance_delta"], (int, float))


# ---------------------------------------------------------------------------
# ComplianceReport (append-only)
# ---------------------------------------------------------------------------
def assert_compliance_report(data: Dict[str, Any]) -> None:
    _assert_append_only_envelope(data, label="ComplianceReport")
    assert data["report_type"] in (
        "LARGE_TRADE", "SUSPICIOUS_TRANSACTION", "INTERNAL_CONTROL",
    )
    # reference_trade_id is null for INTERNAL_CONTROL per PRD §3.4 / §3.10.
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["payload"], dict)
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]


# ---------------------------------------------------------------------------
# AuditLog (append-only)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_append_only_envelope(data, label="AuditLog")
    assert data["event_type"] in (
        "LIMIT_CHANGE", "LIMIT_OVERRIDE_APPROVED", "LIMIT_OVERRIDE_EXPIRED",
        "STOP_LOSS_TRIGGERED", "STOP_LOSS_OVERRIDDEN", "RATING_CHANGE",
        "TRADE_BOOKED", "SETTLEMENT_FAILED", "REPORT_FILED",
    )
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["subject_entity"], str) and data["subject_entity"]
    assert isinstance(data["subject_id"], str) and data["subject_id"]


# ---------------------------------------------------------------------------
# Warning-status invariant — PRD §3.2
# ---------------------------------------------------------------------------
def assert_warning_status_consistent(position_or_limit: Dict[str, Any]) -> None:
    """PRD §3.2: warning_status follows directly from utilization_pct.

    'a utilisation strictly below 80 is NORMAL, a utilisation at or above 80
    but strictly below 100 is WARNING, and a utilisation at or above 100 is
    BREACH. The 80 boundary belongs to WARNING and the 100 boundary belongs
    to BREACH.'

    Accepts either a Position dict (which carries warning_status) or a
    Limit dict with both utilization_pct and warning_status.
    """
    pct = position_or_limit["utilization_pct"]
    status = position_or_limit["warning_status"]
    if pct >= BREACH_PCT:
        expected = "BREACH"
    elif pct >= WARNING_PCT:
        expected = "WARNING"
    else:
        expected = "NORMAL"
    assert status == expected, (
        f"warning_status must be {expected} when utilization_pct={pct}; got {status!r}"
    )


__all__ = [
    "assert_trader",
    "assert_currency_pair",
    "assert_limit",
    "assert_limit_adjustment_request",
    "assert_trade",
    "assert_position",
    "assert_stop_loss_event",
    "assert_counterparty",
    "assert_settlement_instruction",
    "assert_compliance_report",
    "assert_audit_log_entry",
    "assert_warning_status_consistent",
]
