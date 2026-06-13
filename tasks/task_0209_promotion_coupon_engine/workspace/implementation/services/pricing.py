"""Pricing calculations (PRD §3.6-§3.7, scaffold §1.3)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.common import sort_by_created


def round_half_up(value):
    """Round a Decimal/number to whole cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cart_lines(cart_id):
    lines = [l for l in db.cart_lines.values() if l["cart_id"] == cart_id]
    return sort_by_created(lines)


def cart_subtotal(cart_id):
    return sum(l["unit_price_cents"] * l["quantity"] for l in cart_lines(cart_id))


def raw_discount_for(promotion, cart_id, subtotal):
    """Compute the pre-ceiling raw discount this promotion would fund on the cart."""
    ptype = promotion["promo_type"]
    if ptype == "PERCENT_OFF":
        return _percent_off(promotion, cart_id)
    if ptype == "BOGO":
        return _bogo(promotion, cart_id)
    if ptype == "THRESHOLD":
        return _threshold(promotion, subtotal)
    return 0


def _percent_off(promotion, cart_id):
    # Per-line rounding FIRST, then sum (PINNED order). Lines in created_at ASC.
    pct = Decimal(str(promotion["percent_off"]))
    total = 0
    for line in cart_lines(cart_id):
        line_total = line["unit_price_cents"] * line["quantity"]
        line_discount = round_half_up(Decimal(line_total) * pct)
        total += line_discount
    return total


def _bogo(promotion, cart_id):
    sku = promotion["bogo_sku"]
    matching = [l for l in cart_lines(cart_id) if l["sku"] == sku]
    total_qty = sum(l["quantity"] for l in matching)
    free_units = total_qty // 2
    if free_units == 0:
        return 0
    # Expand to one price per unit, preserving line created_at order for tie-break.
    unit_prices = []
    for line in matching:  # already created_at ASC
        unit_prices.extend([line["unit_price_cents"]] * line["quantity"])
    # Stable sort ascending by price; equal prices keep insertion (created_at) order.
    unit_prices.sort()
    return sum(unit_prices[:free_units])


def _threshold(promotion, subtotal):
    tiers = promotion.get("threshold_tiers") or []
    eligible = [t for t in tiers if t["min_subtotal_cents"] <= subtotal]
    if not eligible:
        return 0
    best = max(eligible, key=lambda t: t["min_subtotal_cents"])
    return best["discount_cents"]


def applied_applications(cart_id):
    apps = [
        a
        for a in db.cart_applications.values()
        if a["cart_id"] == cart_id and a["status"] == "APPLIED"
    ]
    # Order by the PROMOTION's created_at ASC (waterfall ordering, PRD §3.7).
    return sorted(apps, key=lambda a: db.promotions[a["promotion_id"]]["_seq"])


def reprice_cart(cart):
    """Recompute subtotal, per-application discount (with stacking ceiling), and
    total. Mutates the cart's computed fields and each APPLIED application."""
    cart_id = cart["id"]
    subtotal = cart_subtotal(cart_id)
    cart["subtotal_cents"] = subtotal

    apps = applied_applications(cart_id)

    # STEP 1: raw discount per application.
    for app in apps:
        promo = db.promotions[app["promotion_id"]]
        app["raw_discount_cents"] = raw_discount_for(promo, cart_id, subtotal)

    # STEP 2: ceiling fraction = min non-null max_stacked_discount_pct.
    pcts = [
        db.promotions[a["promotion_id"]]["max_stacked_discount_pct"]
        for a in apps
        if db.promotions[a["promotion_id"]]["max_stacked_discount_pct"] is not None
    ]
    ceiling_cents = None
    if pcts:
        ceiling_pct = min(pcts)
        # STEP 3: ceiling cents rounded half-up once.
        ceiling_cents = round_half_up(Decimal(subtotal) * Decimal(str(ceiling_pct)))

    # STEP 4: distribute.
    sum_raw = sum(a["raw_discount_cents"] for a in apps)
    if ceiling_cents is None or sum_raw <= ceiling_cents:
        for app in apps:
            app["discount_cents"] = app["raw_discount_cents"]
    else:
        remaining = ceiling_cents
        for app in apps:  # promotion created_at ASC
            grant = min(app["raw_discount_cents"], remaining)
            app["discount_cents"] = grant
            remaining -= grant
        # Any remainder lands on the first application by promotion created_at ASC.
        if remaining > 0 and apps:
            apps[0]["discount_cents"] += remaining

    # STEP 5: cart totals.
    total_discount = sum(a["discount_cents"] for a in apps)
    cart["total_discount_cents"] = total_discount
    cart["total_cents"] = max(0, subtotal - total_discount)


def prospective_discount(promotion, cart_id):
    """Discount this single promotion would fund on the cart's CURRENT line state,
    regardless of pricing_status (PRD §3.8 budget headroom). Pre-ceiling raw,
    because the headroom check is per-promotion at apply/lock time."""
    subtotal = cart_subtotal(cart_id)
    return raw_discount_for(promotion, cart_id, subtotal)
