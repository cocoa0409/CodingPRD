"""Sale pricing engine (PRD §3.3, calc A) and refund variants (PRD §3.7, calc B).

All money is integer cents. Discounts floor; tax is SUM-THEN-ROUND half-up,
applied exactly once over the summed taxable base (never per line).
"""
from decimal import Decimal, ROUND_HALF_UP

from errors import (
    err,
    ERR_PROMO_NOT_APPLICABLE,
    ERR_PROMO_NOT_STACKABLE,
    ERR_INSUFFICIENT_POINTS,
)


def round_half_up(numer, denom):
    """round_half_up(numer/denom) -> integer (PRD §2.6 tax discipline)."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def compute_discount(promo, merchandise_subtotal, lines):
    """STEP 2 (PRD §3.3). lines: list of dicts {list_price_cents, quantity}.

    promo is None or an applicable, ACTIVE promotion that meets min_subtotal.
    Caller is responsible for the applicability guards before calling here for
    the actual figure; this routine returns 0 when promo absent/non-ACTIVE/
    below-min, matching calc A.
    """
    if promo is None or promo["status"] != "ACTIVE":
        return 0
    if merchandise_subtotal < promo["min_subtotal_cents"]:
        return 0
    kind = promo["kind"]
    if kind == "PERCENT_OFF":
        return (merchandise_subtotal * promo["value"]) // 100
    if kind == "AMOUNT_OFF":
        return min(promo["value"], merchandise_subtotal)
    if kind == "BOGO_50":
        total = 0
        for ln in lines:
            pairs = ln["quantity"] // 2
            total += pairs * (ln["list_price_cents"] // 2)
        return total
    return 0


def price_basket(lines, promo, redeem_points, account, tax_rate_bps,
                 enforce_guards=True):
    """Run the six-step pricing on a basket of resolved lines.

    Each element of `lines` is a dict with at least:
        list_price_cents, quantity, tax_exempt (bool), loyalty_eligible (bool)
    Returns a dict with all computed cents figures plus per-line allocations.

    enforce_guards: when True, raises the promo/loyalty validation errors in the
    PRD §3.13 order. The order here is: promo applicability -> stacking ->
    loyalty sufficiency, exactly as the validation table prescribes.
    """
    # STEP 1 — merchandise subtotal
    merchandise_subtotal = sum(ln["list_price_cents"] * ln["quantity"] for ln in lines)

    # promo applicability guard (PRD §3.4 / validation priority 11)
    if enforce_guards and promo is not None:
        if promo["status"] != "ACTIVE" or merchandise_subtotal < promo["min_subtotal_cents"]:
            raise err(ERR_PROMO_NOT_APPLICABLE, "Promotion not applicable")

    # STEP 2 — promo discount
    discount = compute_discount(promo, merchandise_subtotal, lines)

    # STEP 3 — post-discount subtotal
    post_discount = merchandise_subtotal - discount

    # STEP 4 — loyalty redemption
    if enforce_guards and redeem_points and redeem_points > 0:
        # stacking guard (priority 12): non-stackable promo that PRODUCED a
        # discount cannot coexist with a loyalty redemption.
        if promo is not None and not promo["stackable"] and discount > 0:
            raise err(ERR_PROMO_NOT_STACKABLE, "Non-stackable promo cannot combine with loyalty redemption")
        # loyalty sufficiency guard (priority 13)
        if redeem_points > post_discount:
            raise err(ERR_INSUFFICIENT_POINTS, "Redeem exceeds post-discount subtotal")
        if account is None or account["points_balance"] < redeem_points:
            raise err(ERR_INSUFFICIENT_POINTS, "Account holds fewer points than requested")

    if redeem_points and redeem_points > 0:
        loyalty_redeemed = min(redeem_points, post_discount)
    else:
        loyalty_redeemed = 0

    # STEP 5 — tax. Allocate (post_discount - loyalty_redeemed) proportionally to
    # each line's pre-discount extended price, summing the NON-tax-exempt shares,
    # then round half-up ONCE over the summed taxable base.
    net_base = post_discount - loyalty_redeemed
    line_alloc = _allocate(lines, net_base, merchandise_subtotal)
    taxable_base = sum(line_alloc[i] for i, ln in enumerate(lines) if not ln["tax_exempt"])
    if tax_rate_bps and taxable_base > 0:
        tax = round_half_up(taxable_base * tax_rate_bps, 10000)
    else:
        tax = 0

    # STEP 6 — total due
    total_due = post_discount - loyalty_redeemed + tax

    return {
        "merchandise_subtotal_cents": merchandise_subtotal,
        "discount_cents": discount,
        "loyalty_redeemed_cents": loyalty_redeemed,
        "tax_cents": tax,
        "total_due_cents": total_due,
        "line_net_alloc": line_alloc,        # share of net_base per line (floored)
        "taxable_base": taxable_base,
        "post_discount_cents": post_discount,
    }


def _allocate(lines, amount, basis_total):
    """Allocate `amount` across lines proportionally to pre-discount extended
    price (list_price_cents * quantity), floored per line (PRD §2.6, §3.3 STEP 5).

    Returns a list parallel to `lines`.
    """
    allocs = []
    if basis_total <= 0:
        return [0 for _ in lines]
    for ln in lines:
        ext = ln["list_price_cents"] * ln["quantity"]
        allocs.append((amount * ext) // basis_total)
    return allocs


def eligible_net(lines, line_net_alloc):
    """PRD §3.8: sum over loyalty_eligible lines of their net share (already
    floored per line in line_net_alloc)."""
    total = 0
    for i, ln in enumerate(lines):
        if ln["loyalty_eligible"]:
            total += line_net_alloc[i]
    return total
