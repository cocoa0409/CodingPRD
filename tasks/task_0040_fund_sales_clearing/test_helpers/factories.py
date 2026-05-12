"""Payload factories -- one per entity, input fields only (PRD §3).

Defaults are sized for arithmetic clarity (NAV=1.0 CNY, fees that round
cleanly at integer cents) so that tests can derive expected fee/share
numbers from the formulas in PRD §3.4 / §3.5 / §3.6 directly.

Every factory accepts ``**overrides`` so a test that needs to control a
specific field (e.g., ``risk_rating="R5"``) can override exactly that
field while inheriting otherwise-passing defaults.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import uuid


# ---------------------------------------------------------------------------
# Unique-id helpers
# ---------------------------------------------------------------------------
def unique_idempotency_key(prefix: str = "idem") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


_FUND_CODE_COUNTER = [100_000]


def unique_fund_code() -> str:
    """Return a fresh six-digit fund_code matching ^[0-9]{6}$ (PRD §3.2)."""
    _FUND_CODE_COUNTER[0] += 1
    if _FUND_CODE_COUNTER[0] > 999_999:
        # Wrap to keep the six-digit invariant; PRD only requires uniqueness
        # within the test run anyway.
        _FUND_CODE_COUNTER[0] = 100_001
    return f"{_FUND_CODE_COUNTER[0]:06d}"


# ---------------------------------------------------------------------------
# Investor factory (PRD §3.1)
# ---------------------------------------------------------------------------
def create_investor_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: legal_name, investor_type, country_code, risk_tolerance,
    tax_resident_status, bank_account_number are the input fields.
    kyc_status starts PENDING and cash_balance_cents starts at 0
    on the server side -- tests do NOT set them at creation."""
    payload: Dict[str, Any] = {
        "legal_name": "Test Investor",
        "investor_type": "INDIVIDUAL",
        "country_code": "CN",
        "risk_tolerance": "C5",
        "tax_resident_status": "DOMESTIC",
        "bank_account_number": "6222020200000000000",
    }
    payload.update(overrides)
    return payload


def credit_cash_payload(amount_cents: int) -> Dict[str, Any]:
    """PRD §3.1: ``amount_cents`` is the only input field for credit-cash."""
    return {"amount_cents": amount_cents}


# ---------------------------------------------------------------------------
# Fee tiers (PRD §3.2)
# ---------------------------------------------------------------------------
def fee_tier(
    min_amount_cents: int,
    max_amount_cents: Optional[int],
    rate_bps: int,
) -> Dict[str, Any]:
    return {
        "min_amount_cents": min_amount_cents,
        "max_amount_cents": max_amount_cents,
        "rate_bps": rate_bps,
    }


def holding_period_tier(
    min_holding_days: int,
    max_holding_days: Optional[int],
    rate_bps: int,
) -> Dict[str, Any]:
    return {
        "min_holding_days": min_holding_days,
        "max_holding_days": max_holding_days,
        "rate_bps": rate_bps,
    }


def default_subscription_tiers() -> List[Dict[str, Any]]:
    """A single open-ended tier with rate=0 bps -- arithmetically the
    front-end variant degenerates to gross == net so the share math is
    exact at NAV=1.0."""
    return [fee_tier(0, None, 0)]


def default_redemption_tiers() -> List[Dict[str, Any]]:
    """Single open-ended tier with rate=0 bps."""
    return [holding_period_tier(0, None, 0)]


# ---------------------------------------------------------------------------
# Fund factory (PRD §3.2)
# ---------------------------------------------------------------------------
def create_fund_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 input fields. Defaults pass tier validity, allow CN, R3."""
    payload: Dict[str, Any] = {
        "fund_code": unique_fund_code(),
        "fund_name": "Test Fund",
        "fund_type": "BOND",
        "risk_rating": "R3",
        "allowed_country_codes": ["CN"],
        "management_fee_bps_annual": 0,
        "custodian_fee_bps_annual": 0,
        "sales_service_fee_bps_annual": 0,
        "subscription_fee_tiers": default_subscription_tiers(),
        "redemption_fee_tiers": default_redemption_tiers(),
        "back_end_load_enabled": False,
        "conversion_fee_bps": 0,
        "large_redemption_threshold_pct_bps": 1_000,
        "min_subscription_amount_cents": 1,
        "max_subscription_amount_cents": None,
        "min_redemption_shares": 1,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# NAV publish payload (PRD §3.4)
# ---------------------------------------------------------------------------
def publish_nav_payload(
    nav_date: str,
    portfolio_market_value_cents: int = 0,
    portfolio_accrued_income_cents: int = 0,
) -> Dict[str, Any]:
    """PRD §3.4 input fields for /funds/{id}/nav/publish."""
    return {
        "nav_date": nav_date,
        "portfolio_market_value_cents": portfolio_market_value_cents,
        "portfolio_accrued_income_cents": portfolio_accrued_income_cents,
    }


def adjust_nav_payload(
    portfolio_market_value_cents: int,
    portfolio_accrued_income_cents: int,
    adjustment_reason: str,
) -> Dict[str, Any]:
    """PRD §3.4: adjustment_reason must be non-empty."""
    return {
        "portfolio_market_value_cents": portfolio_market_value_cents,
        "portfolio_accrued_income_cents": portfolio_accrued_income_cents,
        "adjustment_reason": adjustment_reason,
    }


# ---------------------------------------------------------------------------
# Order factory (PRD §3.3)
# ---------------------------------------------------------------------------
def create_subscribe_order_payload(
    fund_id: str,
    gross_amount_cents: int,
    idempotency_key: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: SUBSCRIBE carries gross_amount_cents and null
    requested_shares / target_fund_id."""
    payload: Dict[str, Any] = {
        "fund_id": fund_id,
        "order_type": "SUBSCRIBE",
        "gross_amount_cents": gross_amount_cents,
        "idempotency_key": idempotency_key or unique_idempotency_key("sub"),
    }
    payload.update(overrides)
    return payload


def create_redeem_order_payload(
    fund_id: str,
    requested_shares: int,
    idempotency_key: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: REDEEM carries requested_shares and null gross_amount /
    target_fund_id."""
    payload: Dict[str, Any] = {
        "fund_id": fund_id,
        "order_type": "REDEEM",
        "requested_shares": requested_shares,
        "idempotency_key": idempotency_key or unique_idempotency_key("red"),
    }
    payload.update(overrides)
    return payload


def create_convert_order_payload(
    fund_id: str,
    target_fund_id: str,
    requested_shares: int,
    idempotency_key: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: CONVERT carries target_fund_id (must differ from fund_id)
    and requested_shares."""
    payload: Dict[str, Any] = {
        "fund_id": fund_id,
        "order_type": "CONVERT",
        "target_fund_id": target_fund_id,
        "requested_shares": requested_shares,
        "idempotency_key": idempotency_key or unique_idempotency_key("cvt"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DividendPlan (PRD §3.6)
# ---------------------------------------------------------------------------
def create_dividend_plan_payload(
    announcement_date: str,
    record_date: str,
    ex_dividend_date: str,
    payment_date: str,
    dividend_per_share_micros: int = 50_000,
    tax_rate_bps_domestic: int = 1_000,
    tax_rate_bps_foreign: int = 2_000,
) -> Dict[str, Any]:
    """PRD §3.6: announcement, record, ex_dividend, payment dates plus
    dividend_per_share_micros and the two tax bps fields."""
    return {
        "announcement_date": announcement_date,
        "record_date": record_date,
        "ex_dividend_date": ex_dividend_date,
        "payment_date": payment_date,
        "dividend_per_share_micros": dividend_per_share_micros,
        "tax_rate_bps_domestic": tax_rate_bps_domestic,
        "tax_rate_bps_foreign": tax_rate_bps_foreign,
    }


def set_distribution_option_payload(option: str) -> Dict[str, Any]:
    """PRD §3.6: option is CASH or REINVEST."""
    return {"option": option}


# ---------------------------------------------------------------------------
# Reconciliation (PRD §3.7)
# ---------------------------------------------------------------------------
def external_record(
    ref_id: str,
    side: str = "CREDIT",
    amount_cents: int = 0,
    shares: int = 0,
) -> Dict[str, Any]:
    return {
        "ref_id": ref_id,
        "side": side,
        "amount_cents": amount_cents,
        "shares": shares,
    }


def create_reconciliation_payload(
    as_of_date: str,
    scope: str = "TA_VS_CUSTODIAN",
    external_records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """PRD §3.7 inputs."""
    return {
        "as_of_date": as_of_date,
        "scope": scope,
        "external_records": external_records or [],
    }


def adjust_exception_payload(adjustment_amount_cents: int) -> Dict[str, Any]:
    """PRD §3.7: adjustment_amount_cents is the corrective amount."""
    return {"adjustment_amount_cents": adjustment_amount_cents}


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.12)
# ---------------------------------------------------------------------------
def advance_clock_payload(now_iso: str) -> Dict[str, Any]:
    return {"now": now_iso}


__all__ = [
    "unique_idempotency_key",
    "unique_fund_code",
    "create_investor_payload",
    "credit_cash_payload",
    "fee_tier",
    "holding_period_tier",
    "default_subscription_tiers",
    "default_redemption_tiers",
    "create_fund_payload",
    "publish_nav_payload",
    "adjust_nav_payload",
    "create_subscribe_order_payload",
    "create_redeem_order_payload",
    "create_convert_order_payload",
    "create_dividend_plan_payload",
    "set_distribution_option_payload",
    "external_record",
    "create_reconciliation_payload",
    "adjust_exception_payload",
    "advance_clock_payload",
]
