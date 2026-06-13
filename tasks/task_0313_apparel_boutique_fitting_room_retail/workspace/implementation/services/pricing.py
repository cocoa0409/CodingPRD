"""Markdown pricing, loyalty tiers, order pricing, and loyalty accrual
(scaffold §1.3 calculations)."""
from services.money import round_half_up, MIN_PRICE_CENTS

# Loyalty tier thresholds (calc loyalty_tier_eval)
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 150000

# Tier discount basis points (calc order_pricing)
TIER_DISCOUNT_BPS = {"STANDARD": 0, "SILVER": 500, "GOLD": 1000}

# Loyalty accrual (calc loyalty_accrual)
POINTS_DIVISOR_CENTS = 100


# ---------------------------------------------------------------------------
# markdown_pricing (dual-variant #1)
# ---------------------------------------------------------------------------

def markdown_price(style, phase, markdown_pct):
    """Compute a markdown price against the style's CURRENT state.

    SEASONAL marks off list price. CLEARANCE stacks on the live seasonal price
    when one is active (current_price_cents < list_price_cents), else list price.
    Round half-up at the single multiplication step, then floor at MIN_PRICE_CENTS.
    """
    base = style["list_price_cents"]
    if phase == "CLEARANCE":
        seasonal_basis = (
            style["current_price_cents"]
            if style["current_price_cents"] < base
            else base
        )
        price = round_half_up(seasonal_basis * (100 - markdown_pct), 100)
    else:  # SEASONAL
        price = round_half_up(base * (100 - markdown_pct), 100)
    return max(price, MIN_PRICE_CENTS)


# ---------------------------------------------------------------------------
# loyalty_tier_eval (dual-variant #2)
# ---------------------------------------------------------------------------

def tier_for_spend(captured_spend_cents):
    """Boundary-exact thresholds (>=)."""
    if captured_spend_cents >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if captured_spend_cents >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "STANDARD"


# ---------------------------------------------------------------------------
# order_pricing (combinatorial mode b: per-line-then-sum)
# ---------------------------------------------------------------------------

def price_order(lines, tier, tax_rate_bps):
    """Compute subtotal, loyalty_discount, tax. (store_credit/total at capture.)

    Line products are exact integers; subtotal is their sum. Discount and tax
    are each rounded once over the summed amount, never per line.
    """
    subtotal = sum(line["unit_price_cents"] * line["qty"] for line in lines)
    disc_rate_bps = TIER_DISCOUNT_BPS.get(tier, 0)
    loyalty_discount = round_half_up(subtotal * disc_rate_bps, 10000)
    taxable = subtotal - loyalty_discount
    tax = round_half_up(taxable * tax_rate_bps, 10000)
    return subtotal, loyalty_discount, tax


# ---------------------------------------------------------------------------
# loyalty_accrual (combinatorial mode c: pinned evaluation order)
# ---------------------------------------------------------------------------

def mint_points(total_cents):
    """Floor of net cash / 100. Store-credit-funded cents earn nothing because
    total_cents is already net of store_credit_applied."""
    return total_cents // POINTS_DIVISOR_CENTS


def reverse_points_for_line(points_earned, line_total_cents, subtotal_cents):
    """Prorated clawback: points_earned * (line_total / subtotal), round half-up."""
    if subtotal_cents <= 0:
        return 0
    return round_half_up(points_earned * line_total_cents, subtotal_cents)
