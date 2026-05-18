"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / date helpers — PRD §2.4 format with three fractional
# digits. PRD §2.10 wash window keys off UTC calendar dates.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_instant_utc(year: int, month: int, day: int, hour: int = 12,
                    minute: int = 0, second: int = 0) -> str:
    """Build a deterministic ISO 8601 UTC instant with .000Z millis."""
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            tzinfo=timezone.utc))


def iso_date(d: date) -> str:
    """PRD §3.1: 'an ISO 8601 calendar date'."""
    return d.isoformat()


def date_offset(d: date, *, days: int) -> date:
    return d + timedelta(days=days)


def iso_offset(*, days: int = 0, hours: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(days=days, hours=hours))


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def quarter_key_of(d: date) -> str:
    """PRD §3.8: format 'YYYY-Qn' (e.g., '2026-Q2')."""
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


# ---------------------------------------------------------------------------
# Random helpers — keep tickers / suffixes unique across tests.
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_ticker(prefix: str = "T") -> str:
    """PRD §3.9: 'a ticker of between one and ten uppercase characters,
    unique across the catalog'."""
    suffix = random_suffix(4)
    return f"{prefix}{suffix}"[:10]


def random_group_id() -> str:
    return f"group-{random_suffix(6)}"


# ---------------------------------------------------------------------------
# Version body — for OCC-aware mutations.
# ---------------------------------------------------------------------------
def version_body(version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §2.5: optional version field for OCC-aware mutations."""
    return {"version": version} if version is not None else {}


# ===========================================================================
# Client — PRD §3.1
# ===========================================================================
def create_client_payload(
    *,
    full_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    time_horizon_years: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /clients body = {full_name, birth_date,
    time_horizon_years}.
    """
    body: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"{TEST_DEFAULTS['FULL_NAME']} {random_suffix(4)}"
        ),
        "birth_date": (
            birth_date if birth_date is not None
            else TEST_DEFAULTS["BIRTH_DATE"]
        ),
        "time_horizon_years": (
            time_horizon_years if time_horizon_years is not None
            else TEST_DEFAULTS["TIME_HORIZON_YEARS"]
        ),
    }
    body.update(overrides)
    return body


def patch_client_payload(
    *,
    full_name: Optional[str] = None,
    time_horizon_years: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: PATCH /clients body = {full_name?, time_horizon_years?,
    version?}."""
    body: Dict[str, Any] = {}
    if full_name is not None:
        body["full_name"] = full_name
    if time_horizon_years is not None:
        body["time_horizon_years"] = time_horizon_years
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Risk questionnaire — PRD §3.1
# ===========================================================================
def create_questionnaire_payload(
    *,
    q1_loss_tolerance: int = 3,
    q2_volatility_comfort: int = 3,
    q3_growth_vs_stability: int = 3,
    q4_liquidity_need: int = 3,
    q5_experience: int = 3,
    scoring_method: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /clients/{id}/risk-questionnaire body =
    {q1..q5, scoring_method?}.
    """
    body: Dict[str, Any] = {
        "q1_loss_tolerance": q1_loss_tolerance,
        "q2_volatility_comfort": q2_volatility_comfort,
        "q3_growth_vs_stability": q3_growth_vs_stability,
        "q4_liquidity_need": q4_liquidity_need,
        "q5_experience": q5_experience,
    }
    if scoring_method is not None:
        body["scoring_method"] = scoring_method
    body.update(overrides)
    return body


# ===========================================================================
# Model portfolio — PRD §3.2
# ===========================================================================
def create_model_portfolio_payload(
    *,
    risk_band: str = "MODERATE",
    horizon_band: str = "MID",
    target_allocation: Optional[Dict[str, float]] = None,
    is_active: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /model-portfolios body =
    {risk_band, horizon_band, target_allocation, is_active?}.
    """
    body: Dict[str, Any] = {
        "risk_band": risk_band,
        "horizon_band": horizon_band,
        "target_allocation": (
            target_allocation if target_allocation is not None
            else dict(TEST_DEFAULTS["MODEL_ALLOCATION"])
        ),
    }
    if is_active is not None:
        body["is_active"] = is_active
    body.update(overrides)
    return body


# ===========================================================================
# Security — PRD §3.9
# ===========================================================================
def create_security_payload(
    *,
    ticker: Optional[str] = None,
    asset_class: str = "US_EQUITY",
    substantially_identical_group_id: Optional[str] = None,
    is_investable: Optional[bool] = None,
    last_price_cents: int = TEST_DEFAULTS["SECURITY_PRICE_CENTS"],
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /securities body = {ticker, asset_class,
    substantially_identical_group_id, is_investable?, last_price_cents}.
    """
    body: Dict[str, Any] = {
        "ticker": ticker if ticker is not None else random_ticker(),
        "asset_class": asset_class,
        "substantially_identical_group_id": (
            substantially_identical_group_id
            if substantially_identical_group_id is not None
            else random_group_id()
        ),
        "last_price_cents": last_price_cents,
    }
    if is_investable is not None:
        body["is_investable"] = is_investable
    body.update(overrides)
    return body


def set_pricing_payload(security_id: str,
                        last_price_cents: int) -> Dict[str, Any]:
    """PRD §4: POST /_pricing/set body = {security_id, last_price_cents}.
    """
    return {
        "security_id": security_id,
        "last_price_cents": last_price_cents,
    }


# ===========================================================================
# Correlation link — PRD §3.9
# ===========================================================================
def create_correlation_link_payload(
    *,
    security_a_id: str,
    security_b_id: str,
    correlation: float = 0.95,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /correlation-links body =
    {security_a_id, security_b_id, correlation}.
    """
    body: Dict[str, Any] = {
        "security_a_id": security_a_id,
        "security_b_id": security_b_id,
        "correlation": correlation,
    }
    body.update(overrides)
    return body


# ===========================================================================
# Account — PRD §3.3
# ===========================================================================
def create_account_payload(*, client_id: str,
                           **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /accounts body = {client_id}."""
    body: Dict[str, Any] = {"client_id": client_id}
    body.update(overrides)
    return body


def cash_deposit_payload(*, amount_cents: int,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/cash-deposit body = {amount_cents}.
    """
    body: Dict[str, Any] = {"amount_cents": amount_cents}
    body.update(overrides)
    return body


# ===========================================================================
# Trade — PRD §3.4
# ===========================================================================
def create_trade_payload(
    *,
    security_id: str,
    side: str,
    requested_shares: float,
    cost_basis_method: Optional[str] = None,
    specific_lot_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/trades body = {security_id, side,
    requested_shares, cost_basis_method?, specific_lot_id?}.
    """
    body: Dict[str, Any] = {
        "security_id": security_id,
        "side": side,
        "requested_shares": requested_shares,
    }
    if cost_basis_method is not None:
        body["cost_basis_method"] = cost_basis_method
    if specific_lot_id is not None:
        body["specific_lot_id"] = specific_lot_id
    body.update(overrides)
    return body


def cancel_trade_payload(*, version: Optional[int] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/trades/{tid}/cancel body =
    {version?}.
    """
    body: Dict[str, Any] = {}
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ===========================================================================
# Positions — PRD §3.7
# ===========================================================================
def recompute_positions_payload(
    *,
    intent: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/positions/recompute body = {intent?}.
    PRD §3.7: 'when the caller's intent query parameter is detect (the
    default intent is refresh)'.
    """
    body: Dict[str, Any] = {}
    if intent is not None:
        body["intent"] = intent
    body.update(overrides)
    return body


# ===========================================================================
# Rebalance — PRD §3.8
# ===========================================================================
def start_rebalance_payload(
    *,
    quarter_key: str,
    force: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/rebalance/start body =
    {quarter_key, force?}.
    """
    body: Dict[str, Any] = {"quarter_key": quarter_key}
    if force is not None:
        body["force"] = force
    body.update(overrides)
    return body


# ===========================================================================
# Dividend — PRD §3.10
# ===========================================================================
def record_dividend_payload(
    *,
    security_id: str,
    amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §4: POST /accounts/{id}/dividends body =
    {security_id, amount_cents}.
    """
    body: Dict[str, Any] = {
        "security_id": security_id,
        "amount_cents": amount_cents,
    }
    body.update(overrides)
    return body


# ===========================================================================
# Form 1099-B — PRD §3.11
# ===========================================================================
def create_form_1099b_payload(*, tax_year: int,
                              **overrides: Any) -> Dict[str, Any]:
    """PRD §4: POST /clients/{id}/forms-1099b body = {tax_year}."""
    body: Dict[str, Any] = {"tax_year": tax_year}
    body.update(overrides)
    return body


# ===========================================================================
# Clock — PRD §3.12
# ===========================================================================
def clock_advance_payload(*, to_iso: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.12: 'sets the logical clock to the instant supplied as an
    optional to_iso body parameter (when omitted, the clock advances by
    one tick)'.
    """
    body: Dict[str, Any] = {}
    if to_iso is not None:
        body["to_iso"] = to_iso
    body.update(overrides)
    return body


__all__ = [
    # Time helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_date",
    "date_offset",
    "iso_offset",
    "parse_iso",
    "quarter_key_of",
    "random_suffix",
    "random_ticker",
    "random_group_id",
    "version_body",
    # Payload factories
    "create_client_payload",
    "patch_client_payload",
    "create_questionnaire_payload",
    "create_model_portfolio_payload",
    "create_security_payload",
    "set_pricing_payload",
    "create_correlation_link_payload",
    "create_account_payload",
    "cash_deposit_payload",
    "create_trade_payload",
    "cancel_trade_payload",
    "recompute_positions_payload",
    "start_rebalance_payload",
    "record_dividend_payload",
    "create_form_1099b_payload",
    "clock_advance_payload",
]
