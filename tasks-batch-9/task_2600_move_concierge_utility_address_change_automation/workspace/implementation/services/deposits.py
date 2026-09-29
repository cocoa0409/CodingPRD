"""Calculation 3: credit_deposit_amount_cents (both variants)."""

from decimal import Decimal

import db
from services import enums


def band_for_score(score):
    if score >= enums.CREDIT_CLEAR_FLOOR:
        return "CLEAR"
    if score >= enums.CREDIT_DEPOSIT_FLOOR:
        return "DEPOSIT_REQUIRED"
    return "DECLINED"


def base_cents(provider):
    policy = provider["deposit_policy"]
    if policy == "FLAT":
        return Decimal(provider["flat_deposit_cents"])
    if policy == "CREDIT_SCORE_BASED":
        return Decimal(enums.CREDIT_SCORE_BASED_BASE_CENTS)
    return Decimal(0)


def score_multiplier(score):
    if score is None:
        return Decimal("1.50")
    if 580 <= score <= 599:
        return Decimal("1.50")
    if 600 <= score <= 619:
        return Decimal("1.25")
    return Decimal("1.00")


def readiness_multiplier(readiness_snapshot):
    """Reads the frozen snapshot only — never the live readiness score."""
    if readiness_snapshot is None:
        return Decimal("1.00")
    if readiness_snapshot < 50:
        return Decimal("1.20")
    if readiness_snapshot <= 79:
        return Decimal("1.00")
    return Decimal("0.90")


def _capped(product):
    cents = int(db.round_money(product, 0))
    return min(cents, enums.DEPOSIT_CAP_CENTS)


def deposit_amount(provider, score, readiness_snapshot):
    """The at_bureau_response variant."""
    product = base_cents(provider) * score_multiplier(score) * readiness_multiplier(
        readiness_snapshot
    )
    return _capped(product)


def deposit_estimate(provider):
    """The estimate_at_mapping variant: worst-case score band, neutral readiness."""
    product = base_cents(provider) * Decimal("1.50") * Decimal("1.00")
    return _capped(product)
