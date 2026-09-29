"""Shelf pricing and price-staleness propagation (PRD §3.4, §3.3 hop 3-4)."""

from calc import (D, exceeds_reprice_threshold, price_variance_pct, rhu,
                  shelf_price_from_basis)
from db import db, mark

SHELF_LIFE_FIELD = {
    "GROUND": "shelf_life_days_ground",
    "WHOLE_MUSCLE": "shelf_life_days_whole_muscle",
    "VAC_PACKED": "shelf_life_days_vac_packed",
}

PRICEABLE_STATUSES = ("PROPOSED", "PRICED", "REPRICE_REQUIRED")


def base_margin_for(item, department):
    """The item's own override when present, else the department's target."""
    if item.get("target_margin_pct") is not None:
        return D(item["target_margin_pct"])
    return D(department["target_margin_pct"])


def price_for(item, department, cost_basis_cents):
    return shelf_price_from_basis(cost_basis_cents, base_margin_for(item, department))


def shelf_life_for(item, department):
    return department[SHELF_LIFE_FIELD[item["product_class"]]]


def lines_referencing(item_id):
    return [line for line in db.case_plan_lines.values()
            if line["retail_item_id"] == item_id]


def flag_stale_lines(item):
    """Cascade hop 4: published plan lines pointing at a repriced item."""
    for line in lines_referencing(item["id"]):
        plan = db.case_plans.get(line["case_plan_id"])
        if plan is None or plan["plan_status"] != "PUBLISHED":
            continue
        if line["price_stale"]:
            continue
        line["price_stale"] = True
        mark(line)
        plan["price_stale_line_count"] = plan["price_stale_line_count"] + 1
        mark(plan)


def clear_stale_lines(item):
    """Activation clears the staleness flags the item may have inherited."""
    for line in lines_referencing(item["id"]):
        if not line["price_stale"]:
            continue
        line["price_stale"] = False
        mark(line)
        plan = db.case_plans.get(line["case_plan_id"])
        if plan is not None:
            plan["price_stale_line_count"] = max(0, plan["price_stale_line_count"] - 1)
            mark(plan)


def recompute_final_after_cost_change(item, department):
    """Cascade hop 3 (also used by grind-run completion).

    Only an item currently in ``PRICED`` is touched: its final price is
    refreshed, and when it drifts more than two percent from the price actually
    charged the item moves ``PRICED -> REPRICE_REQUIRED`` while the stale price
    stays live at the scale.
    """
    if item["price_status"] != "PRICED":
        return
    new_final = price_for(item, department, item["yield_adjusted_cost_per_lb_cents"])
    item["final_price_per_lb_cents"] = new_final
    mark(item)
    if exceeds_reprice_threshold(new_final, item["active_price_per_lb_cents"]):
        item["price_status"] = "REPRICE_REQUIRED"
        flag_stale_lines(item)


def apply_provisional(item, department, purchase):
    from calc import STANDARD_SALABLE_YIELD_PCT, provisional_cost_basis

    basis = provisional_cost_basis(purchase["invoice_cost_cents"],
                                   purchase["net_weight_lb"])
    item["pricing_yield_pct_snapshot"] = rhu(STANDARD_SALABLE_YIELD_PCT, 4)
    item["shelf_life_days"] = shelf_life_for(item, department)
    price = price_for(item, department, basis)
    item["provisional_price_per_lb_cents"] = price
    item["active_price_per_lb_cents"] = price
    item["price_status"] = "PROPOSED"
    mark(item)


def apply_final(item, department, snapshot_yield_pct, coo_label):
    basis = item["yield_adjusted_cost_per_lb_cents"]
    if snapshot_yield_pct is not None:
        item["pricing_yield_pct_snapshot"] = rhu(snapshot_yield_pct, 4)
    price = price_for(item, department, basis)
    item["final_price_per_lb_cents"] = price
    item["active_price_per_lb_cents"] = price
    item["price_variance_pct"] = price_variance_pct(
        price, item["provisional_price_per_lb_cents"])
    if coo_label is not None:
        item["country_of_origin_label"] = coo_label
    item["price_status"] = "PRICED"
    mark(item)
