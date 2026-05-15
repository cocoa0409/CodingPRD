"""Payload factories — one per entity, input fields only (PRD §3 / §4).

Every factory emits the exact PRD-named fields with sensible defaults;
overrides via kwargs let tests pin specific values.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------
def create_trader_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /fx-risk/traders — PRD §3.1 inputs."""
    payload: Dict[str, Any] = {
        "name": "Test Trader",
        "desk_code": TEST_DEFAULTS["DESK_CODE"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Currency pair
# ---------------------------------------------------------------------------
def create_currency_pair_payload(**overrides: Any) -> Dict[str, Any]:
    """POST /fx-risk/currency-pairs — PRD §3.1 inputs."""
    payload: Dict[str, Any] = {
        "code": TEST_DEFAULTS["PAIR_CODE"],
        "base_ccy": TEST_DEFAULTS["PAIR_BASE"],
        "quote_ccy": TEST_DEFAULTS["PAIR_QUOTE"],
        "mid_rate": TEST_DEFAULTS["PAIR_MID_RATE"],
        "daily_volatility": TEST_DEFAULTS["PAIR_VOL"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Market quote
# ---------------------------------------------------------------------------
def post_market_quote_payload(code: str, mid_rate: float) -> Dict[str, Any]:
    """POST /fx-risk/market-data/quote — PRD §3.1."""
    return {"code": code, "mid_rate": mid_rate}


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------
def create_limit_payload(
    bucket: str,
    notional_cap_usd: float,
    *,
    pair_code: Optional[str] = None,
    stop_loss_cap_usd: float = TEST_DEFAULTS["STOP_LOSS_CAP_USD"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/traders/{trader_id}/limits — PRD §3.2."""
    payload: Dict[str, Any] = {
        "bucket": bucket,
        "notional_cap_usd": notional_cap_usd,
        "stop_loss_cap_usd": stop_loss_cap_usd,
    }
    if pair_code is not None:
        payload["pair_code"] = pair_code
    payload.update(overrides)
    return payload


def patch_limit_payload(
    *,
    version: int,
    notional_cap_usd: Optional[float] = None,
    stop_loss_cap_usd: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /fx-risk/limits/{id} — PRD §3.2."""
    payload: Dict[str, Any] = {"version": version}
    if notional_cap_usd is not None:
        payload["notional_cap_usd"] = notional_cap_usd
    if stop_loss_cap_usd is not None:
        payload["stop_loss_cap_usd"] = stop_loss_cap_usd
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Limit adjustment
# ---------------------------------------------------------------------------
def create_limit_adjustment_payload(
    limit_id: str,
    requested_delta_usd: float,
    *,
    justification: str = "Test override request",
    expires_at: str = TEST_DEFAULTS["EXPIRES_FAR_FUTURE"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/limit-adjustments — PRD §3.3."""
    payload: Dict[str, Any] = {
        "limit_id": limit_id,
        "requested_delta_usd": requested_delta_usd,
        "justification": justification,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


def patch_limit_adjustment_payload(
    *,
    version: int,
    requested_delta_usd: Optional[float] = None,
    justification: Optional[str] = None,
    expires_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /fx-risk/limit-adjustments/{id} — PRD §3.3 (resubmit)."""
    payload: Dict[str, Any] = {"version": version}
    if requested_delta_usd is not None:
        payload["requested_delta_usd"] = requested_delta_usd
    if justification is not None:
        payload["justification"] = justification
    if expires_at is not None:
        payload["expires_at"] = expires_at
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Trade
# ---------------------------------------------------------------------------
def create_trade_payload(
    pair_code: str,
    side: str,
    notional_base: float,
    entry_rate: float,
    counterparty_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/trades — PRD §3.4 inputs (executed_at and trading_day
    are server-stamped and never accepted from the caller).
    """
    payload: Dict[str, Any] = {
        "pair_code": pair_code,
        "side": side,
        "notional_base": notional_base,
        "entry_rate": entry_rate,
        "counterparty_id": counterparty_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------
def create_stop_loss_payload(
    trader_id: str,
    pair_code: str,
    rule_mode: str,
    threshold_value: float,
    action: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/stop-loss — PRD §3.5."""
    payload: Dict[str, Any] = {
        "trader_id": trader_id,
        "pair_code": pair_code,
        "rule_mode": rule_mode,
        "threshold_value": threshold_value,
        "action": action,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Counterparty
# ---------------------------------------------------------------------------
def create_counterparty_payload(
    *,
    name: str = "Test Counterparty",
    external_rating: str = "AAA",
    internal_score: int = 90,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/counterparties — PRD §3.6."""
    payload: Dict[str, Any] = {
        "name": name,
        "external_rating": external_rating,
        "internal_score": internal_score,
    }
    payload.update(overrides)
    return payload


def patch_counterparty_payload(
    *,
    version: int,
    external_rating: Optional[str] = None,
    internal_score: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /fx-risk/counterparties/{id} — PRD §3.6."""
    payload: Dict[str, Any] = {"version": version}
    if external_rating is not None:
        payload["external_rating"] = external_rating
    if internal_score is not None:
        payload["internal_score"] = internal_score
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Settlement
# ---------------------------------------------------------------------------
def generate_settlements_payload(
    counterparty_id: str,
    value_date: str,
    client_request_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/settlements/generate — PRD §3.7."""
    payload: Dict[str, Any] = {
        "counterparty_id": counterparty_id,
        "value_date": value_date,
        "client_request_id": client_request_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Compliance report
# ---------------------------------------------------------------------------
def create_report_payload(
    report_type: str,
    *,
    reference_trade_id: Optional[str] = None,
    payload_data: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /fx-risk/reports — PRD §3.9 manual filing."""
    payload: Dict[str, Any] = {
        "report_type": report_type,
        "payload": payload_data or {"note": "Manual filing"},
    }
    if reference_trade_id is not None:
        payload["reference_trade_id"] = reference_trade_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance
# ---------------------------------------------------------------------------
def advance_clock_payload(to_iso: str) -> Dict[str, Any]:
    """POST /fx-risk/_clock/advance — PRD §2.12."""
    return {"to_iso": to_iso}


__all__ = [
    "create_trader_payload",
    "create_currency_pair_payload",
    "post_market_quote_payload",
    "create_limit_payload",
    "patch_limit_payload",
    "create_limit_adjustment_payload",
    "patch_limit_adjustment_payload",
    "create_trade_payload",
    "create_stop_loss_payload",
    "create_counterparty_payload",
    "patch_counterparty_payload",
    "generate_settlements_payload",
    "create_report_payload",
    "advance_clock_payload",
]
