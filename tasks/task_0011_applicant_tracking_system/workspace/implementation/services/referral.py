"""Referral-bonus calculations per §1.3."""
from decimal import Decimal

import db
from common import round_half_up_int
from services.diversity import is_underrepresented


LEVEL_BASE = {
    "JUNIOR": 100_000,
    "MID": 200_000,
    "SENIOR": 400_000,
    "STAFF": 600_000,
}


def _band_multiplier(base_salary_cents: int) -> Decimal:
    if base_salary_cents < 10_000_000:
        return Decimal("1.0")
    if base_salary_cents < 15_000_000:
        return Decimal("1.25")
    if base_salary_cents < 20_000_000:
        return Decimal("1.5")
    return Decimal("1.75")


def estimated_amount(offer: dict, candidate: dict, requisition: dict) -> int:
    level_base = LEVEL_BASE[requisition["target_level"]]
    band_mult = _band_multiplier(offer["base_salary_cents"])
    raw = Decimal(level_base) * band_mult
    if is_underrepresented(candidate):
        raw = raw * Decimal("1.20")
    return round_half_up_int(raw)


def payable_amount(offer: dict, candidate: dict, requisition: dict, delay_days: int) -> int:
    """Decay schedule per §1.3 referral_bonus_payable."""
    baseline = estimated_amount(offer, candidate, requisition)
    if delay_days <= 30:
        return baseline
    if delay_days <= 60:
        return round_half_up_int(Decimal(baseline) * Decimal("0.75"))
    if delay_days <= 90:
        return round_half_up_int(Decimal(baseline) * Decimal("0.50"))
    return 0
