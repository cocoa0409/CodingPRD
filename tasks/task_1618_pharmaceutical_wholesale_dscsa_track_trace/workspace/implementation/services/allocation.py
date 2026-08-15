"""Shortage allocation (PRD §3.5, calculations.shortage_allocation).

Waterfall allocation over a competing set evaluated at the start of each
allocate call: C = the purchase orders in CONFIRMED or ALLOCATED that contain
an order line of any status for the shortage product; D = total competing
demand (sum of quantity_requested over those lines); N = |C|.

Lines process in ascending created_at, ties broken by ascending
quantity_requested. Integer floor division throughout (PRD §2.6).
"""
import db
from db import store


def competing_set(product_id):
    """(D, N) for a shortage product, evaluated at the start of the call."""
    order_ids = set()
    demand = 0
    for line in store.order_lines.values():
        if line["product_id"] != product_id:
            continue
        order = store.purchase_orders.get(line["order_id"])
        if order is None:
            continue
        if order["fulfillment_status"] in ("CONFIRMED", "ALLOCATED"):
            order_ids.add(order["id"])
            demand += line["quantity_requested"]
    return demand, len(order_ids)


def open_policy_for(product_id):
    for policy in store.allocation_policies.values():
        if policy["product_id"] == product_id and policy["policy_status"] == "OPEN":
            return policy
    return None


def release_line_hold(line):
    """Add back any units the line already held from a prior allocation run so
    re-runs are idempotent given an unchanged competing set. An EXHAUSTED
    policy whose remaining_units rises above zero flips back to OPEN."""
    prior = line.get("quantity_allocated") or 0
    policy_id = line.get("_alloc_policy_id")
    if prior > 0 and policy_id:
        policy = store.allocation_policies.get(policy_id)
        if policy is not None and policy["policy_status"] in ("OPEN", "EXHAUSTED"):
            policy["remaining_units"] += prior
            if policy["policy_status"] == "EXHAUSTED" and policy["remaining_units"] > 0:
                policy["policy_status"] = "OPEN"
                db.touch(policy)
            else:
                policy["updated_at"] = db.wall_now()
    line["_alloc_policy_id"] = None
    line["quantity_allocated"] = 0


def run_allocation(order):
    """Run shortage allocation over the order's lines. Caller has already
    enforced OCC and the CONFIRMED precondition. Returns nothing; mutates."""
    competing = {}

    def competing_for(product_id):
        if product_id not in competing:
            competing[product_id] = competing_set(product_id)
        return competing[product_id]

    lines = [l for l in store.order_lines.values()
             if l["order_id"] == order["id"]
             and l["line_status"] in ("PENDING", "PARTIALLY_ALLOCATED", "UNFULFILLABLE")]
    lines.sort(key=lambda l: (l.get("created_at", ""), l["quantity_requested"]))

    for line in lines:
        product = store.products[line["product_id"]]
        if product["shortage_status"] == "NORMAL":
            release_line_hold(line)
            line["quantity_allocated"] = line["quantity_requested"]
            line["line_status"] = "ALLOCATED"
            db.touch(line)
            continue

        # SHORTAGE product: release the prior hold before re-granting.
        release_line_hold(line)
        policy = open_policy_for(product["id"])
        if policy is None:
            line["line_status"] = "UNFULFILLABLE"
            db.touch(line)
            continue

        demand, count = competing_for(product["id"])
        if policy["policy_mode"] == "PRO_RATA":
            min_g = policy["min_guarantee_units"]
            distributable = policy["pool_units"] - count * min_g
            grant = min_g + (distributable * line["quantity_requested"]) // demand
            grant = max(0, grant)  # MIN_GRANT_FLOOR
        else:  # EQUAL_SHARE
            grant = policy["pool_units"] // count

        allocated = min(grant, line["quantity_requested"], policy["remaining_units"])
        allocated = max(0, allocated)
        line["quantity_allocated"] = allocated
        line["_alloc_policy_id"] = policy["id"] if allocated > 0 else None
        policy["remaining_units"] -= allocated
        if policy["remaining_units"] == 0 and policy["policy_status"] == "OPEN":
            policy["policy_status"] = "EXHAUSTED"
        policy["updated_at"] = db.wall_now()

        if allocated == line["quantity_requested"]:
            line["line_status"] = "ALLOCATED"
        elif allocated > 0:
            line["line_status"] = "PARTIALLY_ALLOCATED"
        else:
            line["line_status"] = "UNFULFILLABLE"
        db.touch(line)


def release_order_allocations(order):
    """Cancel release: return the units each line holds to the policy that
    granted them (OPEN or EXHAUSTED; EXHAUSTED flips back to OPEN when
    remaining_units rises above 0, version incrementing on that release)."""
    for line in store.order_lines.values():
        if line["order_id"] != order["id"]:
            continue
        held = line.get("quantity_allocated") or 0
        policy_id = line.get("_alloc_policy_id")
        if held > 0 and policy_id:
            policy = store.allocation_policies.get(policy_id)
            if policy is not None and policy["policy_status"] in ("OPEN", "EXHAUSTED"):
                was_exhausted = policy["policy_status"] == "EXHAUSTED"
                policy["remaining_units"] += held
                if was_exhausted and policy["remaining_units"] > 0:
                    policy["policy_status"] = "OPEN"
                    db.touch(policy)
                else:
                    policy["updated_at"] = db.wall_now()
        line["_alloc_policy_id"] = None
