"""Pricing calculations (PRD §2.5, §3.3, §3.4).

All monetary amounts are integer cents. Decimal is used for precision-sensitive
per-unit figures with round-half-up; the margin floor is rounded up (ceil).
Rounding is applied PER UNIT before multiplying by qty (round-then-multiply).
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# hotshot_fee constants (calculations.hotshot_fee)
HOTSHOT_BASE_FEE_CENTS = 2500
HOTSHOT_PER_UNIT_CENTS = 750


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ceil_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_CEILING))


def compute_line_pricing(part: dict, tier: dict, account_type: str, qty: int) -> dict:
    """line_net_pricing — returns the four computed line price fields.

    Wholesale variant: full tier matrix (discount + margin floor) applies.
    Retail/COUNTER variant: discount forced to 0, margin floor never binds,
    so unit_merch_price_cents == list_price_cents.
    """
    lp = Decimal(part["list_price_cents"])
    cost = Decimal(part["cost_cents"])
    core = Decimal(part["core_charge_cents"])

    if account_type == "RETAIL":
        d = Decimal("0")
        cd = Decimal(str(tier["core_discount_pct"]))
        m = Decimal("0")
    else:  # WHOLESALE
        d = Decimal(str(tier["discount_pct"]))
        cd = Decimal(str(tier["core_discount_pct"]))
        m = Decimal(str(tier["min_margin_pct"]))

    # step 1: discounted merchandise price, round-half-up per unit
    discounted = _round_half_up(lp * (Decimal("1") - d))
    # step 2: margin floor, ceil so the floor is never undercut
    margin_floor = _ceil_cents(cost * (Decimal("1") + m))
    # step 3: net per-unit merch price = max(discounted, floor)
    unit_merch = max(discounted, margin_floor)
    # step 4: net per-unit core price, round-half-up
    unit_core = _round_half_up(core * (Decimal("1") - cd))
    # steps 5,6: extend by qty (after per-unit rounding)
    line_merch_total = unit_merch * qty
    line_core_total = unit_core * qty

    return {
        "unit_merch_price_cents": unit_merch,
        "unit_core_price_cents": unit_core,
        "line_merch_total_cents": line_merch_total,
        "line_core_total_cents": line_core_total,
    }


def recompute_order_rollup(order: dict, lines: list) -> None:
    """order_rollup — sum already-rounded per-line totals over non-CANCELLED lines.

    Mutates order subtotals in place (does NOT touch version — caller decides).
    order_total includes the order's current hotshot_fee_cents.
    """
    merch = sum(
        ln["line_merch_total_cents"] for ln in lines if ln["status"] != "CANCELLED"
    )
    core = sum(
        ln["line_core_total_cents"] for ln in lines if ln["status"] != "CANCELLED"
    )
    order["merchandise_subtotal_cents"] = merch
    order["core_subtotal_cents"] = core
    order["order_total_cents"] = merch + core + order.get("hotshot_fee_cents", 0)


def compute_hotshot_fee(order: dict, lines: list) -> int:
    """hotshot_fee — BASE + PER_UNIT * special_units, computed at allocation.

    Zero when not requested or when there is no non-cancelled special-order line.
    """
    if not order.get("hotshot_requested"):
        return 0
    special_lines = [
        ln for ln in lines if ln["is_special_order"] and ln["status"] != "CANCELLED"
    ]
    if not special_lines:
        return 0
    special_units = sum(ln["qty"] for ln in special_lines)
    return HOTSHOT_BASE_FEE_CENTS + HOTSHOT_PER_UNIT_CENTS * special_units
