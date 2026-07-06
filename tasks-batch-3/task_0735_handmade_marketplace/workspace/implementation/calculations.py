"""Calculation rules from SCAFFOLD 1.3."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

LISTING_FEE_CENTS = 20
TRANSACTION_FEE_PCT = Decimal("0.065")
PAYMENT_PROCESSING_PCT = Decimal("0.03")
PAYMENT_PROCESSING_FLAT_CENTS = 25
RATING_PRIOR_COUNT = 5
RATING_PRIOR_MEAN = Decimal("4.0")


def round_half_up_cents(amount):
    """Round a Decimal amount half-up to whole cents (integer)."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(amount):
    """Round a Decimal to 2 dp using ROUND_HALF_UP; returns float."""
    q = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def compute_order_shipping(listing, variation, quantity, shipping_profile):
    """Returns (item_subtotal_cents, shipping_cents, order_total_cents)."""
    delta = variation["price_delta_cents"] if variation else 0
    per_unit = listing["price_cents"] + delta
    item_subtotal = per_unit * quantity
    sp = shipping_profile
    thr = sp["free_shipping_threshold_cents"]
    if thr > 0 and item_subtotal >= thr:
        shipping = 0
    else:
        shipping = sp["base_cost_cents"] + sp["per_item_cost_cents"] * max(0, quantity - 1)
    total = item_subtotal + shipping
    return item_subtotal, shipping, total


def compute_order_fees(order_total_cents):
    """Returns (order_fee_cents, order_net_cents)."""
    total = Decimal(order_total_cents)
    transaction_fee = round_half_up_cents(TRANSACTION_FEE_PCT * total)
    processing_fee = round_half_up_cents(PAYMENT_PROCESSING_PCT * total) + PAYMENT_PROCESSING_FLAT_CENTS
    order_fee = LISTING_FEE_CENTS + transaction_fee + processing_fee
    order_net = order_total_cents - order_fee
    return order_fee, order_net


def compute_ship_by(paid_at, listing, shipping_profile):
    days = listing["processing_time_days"] if listing["processing_time_days"] > 0 else shipping_profile["processing_time_days"]
    return paid_at + timedelta(days=days)


def compute_material_status(stock_qty, reorder_threshold):
    if stock_qty == 0:
        return "OUT_OF_STOCK"
    if stock_qty <= reorder_threshold:
        return "LOW_STOCK"
    return "IN_STOCK"


def compute_shop_rating(published_reviews):
    """published_reviews: list of review dicts. Returns
    (published_review_count, simple_avg, weighted).
    simple_avg / weighted are None when n == 0, else floats rounded to 2dp."""
    n = len(published_reviews)
    if n == 0:
        return 0, None, None
    s = sum(r["rating"] for r in published_reviews)
    simple = round_half_up_2dp(Decimal(s) / Decimal(n))
    weighted = round_half_up_2dp(
        (Decimal(s) + Decimal(RATING_PRIOR_COUNT) * RATING_PRIOR_MEAN)
        / (Decimal(n) + Decimal(RATING_PRIOR_COUNT))
    )
    return n, simple, weighted
