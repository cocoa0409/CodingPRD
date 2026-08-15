"""Order creation (takeoff conversion) and fulfillment recompute shared by
the takeoffs and orders route modules."""
from db import db
from services.core import create_record, mutate
from services.calculations import (
    compute_order_pricing, active_surge_event_for_branch, order_lines_of,
)


def create_order_from_takeoff(takeoff, branch):
    """Conversion creates a QUOTED order with exactly one OrderLine carrying
    the shingle-bundles component of the estimate (accessory bundles are
    estimate-only). Pricing is provisional at creation; confirmation locks it."""
    job = db["job_accounts"][takeoff["job_account_id"]]
    account = db["contractor_accounts"][job["contractor_account_id"]]
    order = create_record("orders", {
        "job_account_id": job["id"],
        "takeoff_id": takeoff["id"],
        "branch_id": branch["id"],
        "storm_surge_event_id": None,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "delivery_fee_cents": 0,
        "surge_premium_cents": 0,
        "total_cents": 0,
        "fulfillment_status": "UNFULFILLED",
        "payment_status": "UNPAID",
        "status": "QUOTED",
    })
    create_record("order_lines", {
        "order_id": order["id"],
        "product_id": takeoff["product_id"],
        "inventory_lot_id": None,
        "quantity_bundles": takeoff["_shingle_bundles"],
        "delivered_bundles": 0,
        "returned_bundles": 0,
        "unit_price_cents": db["products"][takeoff["product_id"]]["base_price_per_bundle_cents"],
        "extended_price_cents": 0,
    })
    recompute_order_provisional(order)
    return order


def recompute_order_provisional(order):
    """Refresh extended prices, subtotal, discount, surge premium and total
    from current unit prices and the current delivery fee accrual."""
    for line in order_lines_of(order["id"]):
        line["extended_price_cents"] = line["quantity_bundles"] * line["unit_price_cents"]
    branch = db["branches"].get(order["branch_id"])
    job = db["job_accounts"].get(order["job_account_id"])
    account = db["contractor_accounts"].get(job["contractor_account_id"]) if job else None
    surge_event = active_surge_event_for_branch(order["branch_id"])
    compute_order_pricing(order, account, branch, surge_event)


def recompute_fulfillment(order):
    """DELIVERED when every line is fully delivered, else PARTIALLY_DELIVERED
    once anything has arrived (PRD 3.5)."""
    lines = order_lines_of(order["id"])
    if lines and all(l["delivered_bundles"] >= l["quantity_bundles"] for l in lines):
        order["fulfillment_status"] = "DELIVERED"
    elif any(l["delivered_bundles"] > 0 for l in lines):
        order["fulfillment_status"] = "PARTIALLY_DELIVERED"
    else:
        order["fulfillment_status"] = "UNFULFILLED"
