"""Dual-variant discount engine: collects eligible promotions, filters for
stacking, orders by shop strategy, and applies sequentially."""

from datetime import datetime, timezone

import db
from config import MIN_ORDER_TOTAL
from money import round_money


def calculate_discount(shop, order_items_with_products, subtotal):
    """Calculate discount for an order.

    Args:
        shop: shop dict (must include discount_strategy)
        order_items_with_products: list of dicts, each with at least
            ``product`` (containing ``category``), ``quantity``, ``unit_price``
        subtotal: pre-discount order subtotal (float)

    Returns:
        (discount_amount, applied_promotions) where applied_promotions is a list
        of {promotion_id, promo_type, discount_contribution}.
    """
    now = datetime.now(timezone.utc).isoformat()

    # --- 1. Collect eligible ACTIVE promotions for this shop ---
    all_promos = db.find_many("promotions", shop_id=shop["id"], status="ACTIVE")

    order_categories = set()
    for item in order_items_with_products:
        cat = item.get("product", {}).get("category")
        if cat:
            order_categories.add(cat)

    total_quantity = sum(it["quantity"] for it in order_items_with_products)

    eligible = []
    for promo in all_promos:
        # Time window
        if promo.get("start_time") and promo["start_time"] > now:
            continue
        if promo.get("end_time") and promo["end_time"] <= now:
            continue

        # Category applicability
        applicable_cats = promo.get("applicable_categories") or []
        if applicable_cats and not order_categories.intersection(applicable_cats):
            continue

        # Usage cap
        max_usage = promo.get("max_usage")
        if max_usage is not None and promo.get("usage_count", 0) >= max_usage:
            continue

        # Threshold
        promo_type = promo["promo_type"]
        threshold = promo.get("promo_threshold", 0) or 0
        if promo_type in ("PERCENTAGE", "FIXED_AMOUNT"):
            if subtotal < threshold:
                continue
        elif promo_type == "BUY_X_GET_Y_FREE":
            if total_quantity < threshold:
                continue

        eligible.append(promo)

    if not eligible:
        return 0.0, []

    # --- 2. Filter for stacking ---
    stackable = [p for p in eligible if p.get("stackable", False)]
    non_stackable = [p for p in eligible if not p.get("stackable", False)]

    chosen_non_stackable = None
    if non_stackable:
        # Keep the one with highest priority (lowest number)
        non_stackable.sort(key=lambda p: p.get("priority", 999))
        chosen_non_stackable = non_stackable[0]

    promos_to_apply = list(stackable)
    if chosen_non_stackable:
        promos_to_apply.append(chosen_non_stackable)

    # --- 3. Sort by discount_strategy ---
    strategy = shop.get("discount_strategy", "PERCENTAGE_FIRST")

    type_order = {
        "PERCENTAGE_FIRST": {"PERCENTAGE": 0, "FIXED_AMOUNT": 1, "BUY_X_GET_Y_FREE": 2},
        "FIXED_FIRST": {"FIXED_AMOUNT": 0, "PERCENTAGE": 1, "BUY_X_GET_Y_FREE": 2},
    }.get(strategy, {"PERCENTAGE": 0, "FIXED_AMOUNT": 1, "BUY_X_GET_Y_FREE": 2})

    promos_to_apply.sort(
        key=lambda p: (type_order.get(p["promo_type"], 9), p.get("priority", 999))
    )

    # --- 4. Apply sequentially ---
    running_total = subtotal
    applied = []

    for promo in promos_to_apply:
        if running_total <= MIN_ORDER_TOTAL:
            break

        promo_type = promo["promo_type"]
        promo_value = promo.get("promo_value", 0) or 0
        discount = 0.0

        if promo_type == "PERCENTAGE":
            discount = running_total * promo_value / 100.0
            max_cap = promo.get("max_discount_cap")
            if max_cap is not None and discount > max_cap:
                discount = max_cap

        elif promo_type == "FIXED_AMOUNT":
            discount = min(promo_value, running_total)

        elif promo_type == "BUY_X_GET_Y_FREE":
            y = int(promo.get("promo_value", 1) or 1)
            # Collect applicable item unit prices
            applicable_cats = promo.get("applicable_categories") or []
            prices = []
            for item in order_items_with_products:
                cat = item.get("product", {}).get("category")
                if applicable_cats and cat not in applicable_cats:
                    continue
                # Each unit is a separate entry for sorting
                for _ in range(item["quantity"]):
                    prices.append(item["unit_price"])
            # Y cheapest
            prices.sort()
            cheapest = prices[:y]
            discount = sum(cheapest)

        discount = round_money(discount)
        if discount <= 0:
            continue

        # Ensure running_total doesn't go below MIN_ORDER_TOTAL
        max_possible = running_total - MIN_ORDER_TOTAL
        if max_possible <= 0:
            break
        if discount > max_possible:
            discount = round_money(max_possible)

        running_total = round_money(running_total - discount)
        applied.append({
            "promotion_id": promo["id"],
            "promo_type": promo_type,
            "discount_contribution": discount,
        })

    total_discount = round_money(sum(a["discount_contribution"] for a in applied))
    return total_discount, applied
