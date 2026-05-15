"""Numeric calculations: FX, tax withholding, prize allocation, contagion risk."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


# FX rates per PRD §3.6. Source currency -> destination currency -> rate.
FX_RATE: dict[str, dict[str, float]] = {
    "USD": {"USD": 1.0, "EUR": 0.92, "KRW": 1350.0, "CNY": 7.20},
    "EUR": {"USD": 1.09, "EUR": 1.0, "KRW": 1465.0, "CNY": 7.83},
    "KRW": {"USD": 0.00074, "EUR": 0.00068, "KRW": 1.0, "CNY": 0.0053},
    "CNY": {"USD": 0.139, "EUR": 0.128, "KRW": 187.5, "CNY": 1.0},
}


# Tax brackets per PRD §3.6.
TAX_BRACKETS: dict[str, list[dict[str, int]]] = {
    "US": [
        {"up_to_cents": 100_000_000, "rate_bps": 2400},
        {"up_to_cents": 999_999_999_999, "rate_bps": 3700},
    ],
    "DE": [
        {"up_to_cents": 5_000_000_000, "rate_bps": 4500},
    ],
    "KR": [
        {"up_to_cents": 100_000_000, "rate_bps": 2200},
        {"up_to_cents": 500_000_000, "rate_bps": 3500},
        {"up_to_cents": 999_999_999_999, "rate_bps": 4500},
    ],
    "CN": [
        {"up_to_cents": 999_999_999_999, "rate_bps": 2000},
    ],
}


MVP_BPS = 500  # 5%
MIN_PAYOUT_FLOOR_CENTS = 100
RISK_HALFLIFE_DAYS = 30
AUTO_DISQUALIFY_THRESHOLD = 50


def half_up_int(value: Decimal | float | int) -> int:
    """Round half-up to an integer."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fx_convert(amount_cents: int, from_ccy: str, to_ccy: str) -> int:
    """Half-up rounded FX conversion in minor units."""
    if amount_cents == 0:
        return 0
    if from_ccy == to_ccy:
        return int(amount_cents)
    table = FX_RATE.get(from_ccy)
    if not table or to_ccy not in table:
        # Treat unknown FX as 1:1 to be safe — should never trigger for the four
        # supported currencies but provides defensive failure mode.
        return int(amount_cents)
    rate = Decimal(str(table[to_ccy]))
    result = Decimal(amount_cents) * rate
    return half_up_int(result)


def compute_prize_tier_amount(pool_cents: int, percentage_bps: int) -> int:
    """gross = round_half_up(pool * percentage_bps / 10000), one round per row."""
    if pool_cents <= 0:
        return 0
    raw = Decimal(pool_cents) * Decimal(percentage_bps) / Decimal(10000)
    return half_up_int(raw)


def compute_mvp_amount(pool_cents: int) -> int:
    return compute_prize_tier_amount(pool_cents, MVP_BPS)


def validate_prize_tier_sum(prize_tier_table: list[dict[str, Any]]) -> bool:
    """sum(prize_tier_table.percentage_bps) + MVP_BPS == 10000."""
    total = sum(int(t.get("percentage_bps", 0)) for t in prize_tier_table)
    return total + MVP_BPS == 10000


def compute_tax_withholding(
    gross_cents: int,
    jurisdiction: str,
    entry_fee_currency: str,
    payout_currency: str,
) -> tuple[int, int, int]:
    """Returns (tax_in_payout_ccy, gross_in_payout_ccy, net_in_payout_ccy).

    Walks the bracket walking schedule per PRD §3.6: each slice tax is
    round-half-up at the slice level, then summed. FX happens AFTER tax.
    Floor adjustment lifts net up to MIN_PAYOUT_FLOOR_CENTS where possible.
    """
    bracket = TAX_BRACKETS.get(jurisdiction)
    if bracket is None:
        # Unknown jurisdiction — apply zero tax (treat as defensive default).
        tax_source = 0
    else:
        remaining = gross_cents
        prev = 0
        tax_source = 0
        for tier in bracket:  # already in ascending order in our table
            up_to = int(tier["up_to_cents"])
            rate = int(tier["rate_bps"])
            slice_cents = max(0, min(remaining, up_to) - prev)
            if slice_cents > 0:
                slice_tax = half_up_int(Decimal(slice_cents) * Decimal(rate) / Decimal(10000))
                tax_source += slice_tax
            prev = up_to
            if remaining <= up_to:
                break

    tax_in_payout = fx_convert(tax_source, entry_fee_currency, payout_currency)
    gross_in_payout = fx_convert(gross_cents, entry_fee_currency, payout_currency)
    net = gross_in_payout - tax_in_payout

    if net < MIN_PAYOUT_FLOOR_CENTS:
        delta = MIN_PAYOUT_FLOOR_CENTS - net
        # Reduce tax by up to delta (never below 0); recompute net.
        reducible = min(delta, tax_in_payout)
        tax_in_payout = max(0, tax_in_payout - reducible)
        net = gross_in_payout - tax_in_payout

    return tax_in_payout, gross_in_payout, net


def compute_contagion_delta(penalty_type: str, classification: str) -> Decimal:
    """delta = base_weight(penalty) * classification_multiplier(classification)."""
    base_weight = {
        "WARNING": 1,
        "FINE": 3,
        "FORFEIT": 5,
        "DISQUALIFICATION": 10,
    }.get(penalty_type, 0)
    cls_mult = {
        "LATENCY": Decimal("1.0"),
        "UNSPORTSMANLIKE_CONDUCT": Decimal("1.5"),
        "RULE_VIOLATION": Decimal("2.0"),
        "CHEATING_SUSPICION": Decimal("3.0"),
    }.get(classification, Decimal("0"))
    return Decimal(base_weight) * cls_mult


def apply_contagion_decay(old_risk: int, last_decay: datetime | None, now: datetime) -> Decimal:
    """decayed = old_risk * 0.5^((now - last_decay).days / 30).

    Returns the decayed value as a Decimal (not yet rounded — only round once at the end).
    """
    if old_risk == 0 or last_decay is None:
        return Decimal(old_risk)
    delta = now - last_decay
    days = Decimal(delta.total_seconds()) / Decimal(86400)
    half_life = Decimal(RISK_HALFLIFE_DAYS)
    # 0.5^(days/half_life) — Decimal lacks a native power; use a Taylor-free conversion.
    import math
    exponent = float(days / half_life)
    factor = Decimal(str(0.5 ** exponent))
    return Decimal(old_risk) * factor
