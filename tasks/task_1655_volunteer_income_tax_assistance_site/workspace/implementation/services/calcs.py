"""Calculation rules (SCAFFOLD §1.3, PRD §2.6): integer cents, Decimal math,
round-half-up at each rate multiplication; savings match floors per line first."""
from decimal import Decimal, ROUND_HALF_UP

from db import store

EITC_EST_RATE = Decimal("0.15")
EITC_EST_CAP_CENTS = 600000
TAX_RATE = Decimal("0.12")
MATCH_CAP_CENTS = 10000

_FINAL_TIERS = {
    0: (Decimal("0.10"), 60000),
    1: (Decimal("0.20"), 400000),
}
_FINAL_TOP = (Decimal("0.25"), 650000)  # qualifying_children >= 2


def _rhu(value):
    """Round a Decimal half-up to whole cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimated_refund_cents(ret):
    """Provisional variant (PRD §3.4): reported withholding + capped 15% EITC,
    zero tax liability."""
    eitc = min(_rhu(EITC_EST_RATE * ret["earned_income_cents"]), EITC_EST_CAP_CENTS)
    return ret["withholding_reported_cents"] + eitc


def final_refund_cents(ret):
    """Final variant (PRD §3.5): tiered EITC, flat 12% liability, floor at zero.
    Order pinned: tier rate/cap -> eitc min() -> liability -> refund max()."""
    q = ret["qualifying_children"]
    rate, cap = _FINAL_TIERS.get(q, _FINAL_TOP)
    eitc = min(_rhu(rate * ret["earned_income_cents"]), cap)
    liability = _rhu(TAX_RATE * (ret["wages_cents"] + ret["other_income_cents"]))
    return max(0, ret["withholding_verified_cents"] + eitc - liability)


def savings_match_cents(tax_return_id):
    """Savings match (PRD §3.6): floor EACH SAVINGS line's 50% to whole dollars
    before summation, then cap at $100."""
    total = 0
    for a in store.refund_allocations.values():
        if a["tax_return_id"] == tax_return_id and a["account_type"] == "SAVINGS":
            total += (a["amount_cents"] // 200) * 100
    return min(total, MATCH_CAP_CENTS)


def rate_bp(numerator, denominator):
    """Basis points, integer, round-half-up; None when the denominator is 0."""
    if denominator == 0:
        return None
    return int((Decimal(numerator * 10000) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
