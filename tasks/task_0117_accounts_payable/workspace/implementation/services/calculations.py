"""Calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3.4, §3.7, §3.8).

All monetary amounts are integer cents. Where a non-integer intermediate occurs,
round half-up to the nearest whole cent (round-half-up means exactly-halfway
rounds to the larger cent). Rounding is applied once, on the single product,
before any subtraction or summation.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# Constants pinned in the scaffold calculations table.
ABS_TOLERANCE_CENTS = 1000
PCT_TOLERANCE = Decimal("0.02")
CONFIDENCE_FLOOR = 0.80
WRITEOFF_CEILING_CENTS = 5000


def round_half_up(value: Decimal) -> int:
    """Round a Decimal to the nearest whole cent, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def match_variance(match_type: str, total_amount_cents: int, po: dict) -> int:
    """Variance in cents at match time, basis depends on match_type (PRD §3.4)."""
    if match_type == "NON_PO":
        return 0
    if match_type == "TWO_WAY":
        # 2-way: invoice billed vs PO ordered.
        return total_amount_cents - po["ordered_amount_cents"]
    if match_type == "THREE_WAY":
        # 3-way: invoice billed vs goods RECEIVED (received governs, not ordered).
        return total_amount_cents - po["received_amount_cents"]
    return 0


def match_tolerance_cents(po: dict) -> int:
    """Tolerance = max(abs floor, ordered * pct rounded half-up) (PRD §3.4)."""
    pct_part = round_half_up(Decimal(po["ordered_amount_cents"]) * PCT_TOLERANCE)
    return max(ABS_TOLERANCE_CENTS, pct_part)


def breaches_tolerance(variance_cents: int, tolerance_cents: int) -> bool:
    """Breach only when abs(variance) is STRICTLY greater than tolerance."""
    return abs(variance_cents) > tolerance_cents


def early_pay_discount(total_amount_cents: int, discount_deadline, run_date,
                       early_pay_terms_pct) -> int:
    """discount_taken_cents for a payment (PRD §3.7).

    Zero when vendor offers no discount or deadline is null. Otherwise, when the
    run_date is on or before the discount_deadline (on the deadline still earns
    it), discount = round_half_up(total * pct). Past the deadline => 0.
    """
    if not early_pay_terms_pct or discount_deadline is None:
        return 0
    pct = Decimal(str(early_pay_terms_pct))
    if pct == 0:
        return 0
    if run_date <= discount_deadline:
        raw = Decimal(total_amount_cents) * pct
        return round_half_up(raw)
    return 0


def accrual_amount(po: dict) -> int:
    """ESTIMATE and FINAL share the same formula, evaluated at their own time:
    max(0, received_amount_cents - matched_amount_cents) (PRD §3.8)."""
    return max(0, po["received_amount_cents"] - po["matched_amount_cents"])
