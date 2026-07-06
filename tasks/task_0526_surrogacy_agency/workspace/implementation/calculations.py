"""Calculation rules (scaffold §1.3, PRD §3.2, §3.3, §3.7).

All money is integer cents. Percentage terms use round_half_up on the
Decimal intermediate at the pinned point, then exact integer arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

MULTIPLES_ADDON_CENTS = 500000
TIER1_PCT = Decimal("0.05")
TIER2_PCT = Decimal("0.10")
GAP_RATE_PER_MONTH = Decimal("0.015")
GAP_MONTHS = 9

PHASE_ORDER = {
    "PRE_TRANSFER": 0,
    "TRANSFERRED": 1,
    "HEARTBEAT_CONFIRMED": 2,
    "BORN": 3,
}


def _round_half_up(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def insurance_gap_premium(base_compensation_cents):
    """monthly = round_half_up(base * 0.015); then * 9 (nested order pinned)."""
    monthly = _round_half_up(Decimal(base_compensation_cents) * GAP_RATE_PER_MONTH)
    return monthly * GAP_MONTHS


def experience_bonus(base_cents, prior_deliveries):
    if prior_deliveries is None:
        return 0
    if prior_deliveries == 1:
        return 0
    if 2 <= prior_deliveries <= 3:
        return _round_half_up(Decimal(base_cents) * TIER1_PCT)
    if prior_deliveries >= 4:
        return _round_half_up(Decimal(base_cents) * TIER2_PCT)
    # prior_deliveries == 0 -> no tier applies -> 0
    return 0


def carrier_comp_breakdown(base_cents, prior_deliveries, multiples_addon_applies):
    """Pinned order: experience bonus computed & rounded from base FIRST, then summed."""
    base = int(base_cents)
    bonus = experience_bonus(base, prior_deliveries)
    addon = MULTIPLES_ADDON_CENTS if multiples_addon_applies else 0
    total = base + bonus + addon
    return {
        "base_cents": base,
        "experience_bonus_cents": bonus,
        "multiples_addon_cents": addon,
        "total_cents": total,
    }
