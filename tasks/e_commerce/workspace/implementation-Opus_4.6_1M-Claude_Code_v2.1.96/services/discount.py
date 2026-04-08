import json
from decimal import Decimal, ROUND_HALF_UP
from money import to_decimal, round2, TWO_PLACES


def apply_promotions(subtotal, items, promotions, discount_strategy):
    """
    Apply promotions according to the shop's discount_strategy.
    Returns (discount_amount, total_amount, applied_promotions_list).
    """
    if not promotions:
        return 0.0, round2(subtotal), []

    sub = to_decimal(subtotal)

    # Separate by type
    percentage_promos = []
    fixed_promos = []
    bxgy_promos = []

    for p in promotions:
        pt = p["promo_type"]
        if pt == "PERCENTAGE":
            percentage_promos.append(p)
        elif pt == "FIXED_AMOUNT":
            fixed_promos.append(p)
        elif pt == "BUY_X_GET_Y_FREE":
            bxgy_promos.append(p)

    # Sort each group by priority
    percentage_promos.sort(key=lambda x: x["priority"])
    fixed_promos.sort(key=lambda x: x["priority"])
    bxgy_promos.sort(key=lambda x: x["priority"])

    if discount_strategy == "PERCENTAGE_FIRST":
        ordered = percentage_promos + fixed_promos + bxgy_promos
    else:  # FIXED_FIRST
        ordered = fixed_promos + percentage_promos + bxgy_promos

    running = sub
    min_total = Decimal("0.01")
    applied = []

    for p in ordered:
        if running <= min_total:
            break

        discount = Decimal("0")
        pt = p["promo_type"]

        if pt == "PERCENTAGE":
            pct = to_decimal(p["promo_value"]) / Decimal("100")
            discount = (running * pct).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            if p.get("max_discount_cap") is not None:
                cap = to_decimal(p["max_discount_cap"])
                if discount > cap:
                    discount = cap

        elif pt == "FIXED_AMOUNT":
            discount = to_decimal(p["promo_value"])
            if discount > running:
                discount = running

        elif pt == "BUY_X_GET_Y_FREE":
            y = int(p["promo_value"])
            # Find cheapest Y items from qualifying items
            qualifying_units = []
            for item in items:
                cats = p.get("applicable_categories", [])
                if isinstance(cats, str):
                    cats = json.loads(cats)
                snapshot = item.get("product_snapshot", {})
                if isinstance(snapshot, str):
                    snapshot = json.loads(snapshot)
                item_cat = snapshot.get("category", item.get("category", ""))
                if not cats or item_cat in cats:
                    for _ in range(item["quantity"]):
                        qualifying_units.append(to_decimal(item["unit_price"]))

            qualifying_units.sort()
            free_count = min(y, len(qualifying_units))
            discount = sum(qualifying_units[:free_count], Decimal("0"))

        discount = discount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        # Ensure running doesn't go below min_total
        max_discount = running - min_total
        if discount > max_discount:
            discount = max_discount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

        if discount > 0:
            running -= discount
            applied.append({
                "promotion_id": p["id"],
                "promo_type": pt,
                "discount_contribution": float(discount),
            })

    total_discount = sub - running
    total_discount = total_discount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    total_amount = running.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    if total_amount < min_total:
        total_amount = min_total
        total_discount = (sub - min_total).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return float(total_discount), float(total_amount), applied


def distribute_discount(items, discount_amount, subtotal):
    """
    Distribute discount proportionally across items.
    Last item gets remainder to ensure exact totals.
    Items should be sorted by order_item_id ascending.
    """
    if not items or discount_amount == 0:
        return items

    disc = to_decimal(discount_amount)
    sub = to_decimal(subtotal)
    allocated = Decimal("0")

    sorted_items = sorted(items, key=lambda x: x["id"])

    for i, item in enumerate(sorted_items):
        lt = to_decimal(item["line_total"])
        if i < len(sorted_items) - 1:
            share = (lt / sub * disc).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            allocated += share
        else:
            share = disc - allocated

        item["discount_share"] = float(share)
        item["final_price"] = float((lt - share).quantize(TWO_PLACES, rounding=ROUND_HALF_UP))

    return sorted_items
