"""All algorithmic rules in one place (SCAFFOLD §1.3).

Each function corresponds to a named calculation in the scaffold and is
documented with its rule, precision requirement, and rounding order.
"""
from __future__ import annotations

from datetime import datetime, timezone

import config as cfg
from utils import add_business_days, ceil_term


# ── 1. options_eligibility_max ─────────────────────────────────────────────

def options_eligibility_max(customer: dict) -> int:
    """Highest options level the customer is eligible for (0..4).

    Tier rules from SCAFFOLD; tested top-down so the LAST satisfied tier
    wins (matches the YAML algorithm).
    """
    yrs = int(customer["years_options_experience"])
    lnw = int(customer["liquid_net_worth_cents"])
    tnw = int(customer["total_net_worth_cents"])

    eligible = 0
    if yrs >= 0 and lnw >= cfg.LEVEL_1_LNW_CENTS:
        eligible = 1
    if yrs >= 1 and lnw >= cfg.LEVEL_2_LNW_CENTS:
        eligible = 2
    if yrs >= 2 and lnw >= cfg.LEVEL_3_LNW_CENTS and tnw >= cfg.LEVEL_3_TNW_CENTS:
        eligible = 3
    if yrs >= 3 and lnw >= cfg.LEVEL_4_LNW_CENTS and tnw >= cfg.LEVEL_4_TNW_CENTS:
        eligible = 4
    return eligible


# ── 2. margin_requirement ──────────────────────────────────────────────────

def order_reference_price_cents(order_type: str, limit_price: int | None, stop_price: int | None) -> int | None:
    """Choose the price field that determines notional value.

    LIMIT/STOP_LIMIT/TAKE_PROFIT use limit_price_cents.
    STOP uses stop_price_cents.
    MARKET: caller must supply a market-reference price; here we return
    None and the route layer reads `market_reference_price_cents` or
    falls back to `limit_price_cents` if the client supplied it.
    """
    if order_type in (cfg.ORDER_TYPE_LIMIT, cfg.ORDER_TYPE_STOP_LIMIT, cfg.ORDER_TYPE_TAKE_PROFIT):
        return limit_price
    if order_type == cfg.ORDER_TYPE_STOP:
        return stop_price
    return None


def margin_requirement_cents(
    account_type: str,
    instrument_type: str,
    option_strategy: str | None,
    quantity: int,
    reference_price_cents: int,
) -> int:
    """Compute the initial-margin requirement for an order in cents.

    PRD §3.3 / SCAFFOLD calc 2 — per-term ceiling rounding before
    summation. Naked add-on (20%) only applies on Reg T option orders
    using NAKED_CALL/NAKED_PUT; PMA has no add-on.
    """
    notional = quantity * reference_price_cents
    if notional < 0:
        notional = 0

    if account_type == cfg.ACCOUNT_TYPE_CASH:
        base = notional  # 100% — full cash. Already integer cents.
    elif account_type == cfg.ACCOUNT_TYPE_MARGIN_REG_T:
        base = ceil_term(notional, cfg.REG_T_RATE_NUM, cfg.RATE_DENOM)
    elif account_type == cfg.ACCOUNT_TYPE_MARGIN_PMA:
        base = ceil_term(notional, cfg.PMA_RATE_NUM, cfg.RATE_DENOM)
    else:
        # Unrecognised account_type — treat as no margin so callers can
        # surface the validation error elsewhere; the create-account path
        # also validates account_type up front.
        base = notional

    addon = 0
    if (
        instrument_type == cfg.INSTRUMENT_OPTION
        and option_strategy in cfg.NAKED_STRATEGIES
        and account_type == cfg.ACCOUNT_TYPE_MARGIN_REG_T
    ):
        addon = ceil_term(notional, cfg.NAKED_ADDON_NUM, cfg.RATE_DENOM)

    return base + addon


# ── 3. day_trade_pairing ───────────────────────────────────────────────────

def trade_date_utc(filled_at: datetime) -> str:
    """Convert a filled_at datetime to a YYYY-MM-DD UTC trade date string."""
    if filled_at.tzinfo is None:
        filled_at = filled_at.replace(tzinfo=timezone.utc)
    else:
        filled_at = filled_at.astimezone(timezone.utc)
    return filled_at.date().isoformat()


# ── 4. acat_completion_eta ─────────────────────────────────────────────────

def acat_expected_completion(initiated_at: datetime) -> datetime:
    """Add 6 business days to initiated_at's calendar date, pin to 17:00 UTC."""
    target = add_business_days(initiated_at.date(), cfg.ACAT_BUSINESS_DAYS)
    return datetime(
        target.year,
        target.month,
        target.day,
        cfg.ACAT_COMPLETION_HOUR_UTC,
        0,
        0,
        0,
        tzinfo=timezone.utc,
    )
