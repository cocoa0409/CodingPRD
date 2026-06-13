"""Shared domain operations on GarmentOrder / GroupOrder: recomputation of
derived figures, group recomputation, and the cancellation release cascade."""
from db import db, touch
from services import calculations as calc


# ---------------------------------------------------------------------------
# Option-line / order helpers
# ---------------------------------------------------------------------------

def order_option_lines(order_id):
    lines = [l for l in db.option_lines.values() if l["order_id"] == order_id]
    # created_at ASC, ties broken by created_at again (stable) — sort key created_at.
    lines.sort(key=lambda l: l["created_at"])
    return lines


def first_option_line(order_id):
    lines = order_option_lines(order_id)
    return lines[0] if lines else None


def order_payments(order_id):
    pays = [p for p in db.payments.values() if p["order_id"] == order_id]
    pays.sort(key=lambda p: p["created_at"])
    return pays


def captured_amount(order_id):
    return sum(p["amount_cents"] for p in db.payments.values()
               if p["order_id"] == order_id and p["status"] == "CAPTURED")


def recompute_quote(order):
    """Provisional quote recompute (DRAFT only) using the LIVE fabric price of the
    first option line's fabric."""
    lines = order_option_lines(order["id"])
    if not lines:
        order["quoted_total_cents"] = 0
        return
    first = lines[0]
    fabric = db.fabrics.get(first["fabric_id"])
    live_price = fabric["price_per_meter_cents"] if fabric else first["fabric_price_per_meter_cents"]
    order["quoted_total_cents"] = calc.order_quote_total(
        order["base_labor_cents"],
        order["fabric_meters_required"],
        live_price,
        lines,
        order["is_rush"],
    )


def recompute_balance(order):
    order["amount_paid_cents"] = captured_amount(order["id"])
    order["balance_due_cents"] = calc.balance_due(
        order["locked_total_cents"],
        order["amount_paid_cents"],
        order["store_credit_applied_cents"],
    )


# ---------------------------------------------------------------------------
# Group recomputation
# ---------------------------------------------------------------------------

def group_members(group_id):
    """All non-CANCELLED member orders (for member_order_count)."""
    return [o for o in db.garment_orders.values()
            if o["group_order_id"] == group_id and o["status"] != "CANCELLED"]


def group_total_members(group_id):
    """Members that count toward group_total_cents (CONFIRMED+ states)."""
    return [o for o in db.garment_orders.values()
            if o["group_order_id"] == group_id
            and o["status"] in calc.GROUP_MEMBER_STATES]


def recompute_group(group):
    """Recompute member_order_count and group_total_cents; bump the group's version."""
    members = group_members(group["id"])
    total_members = group_total_members(group["id"])
    group["member_order_count"] = len(members)
    group["group_total_cents"] = calc.group_order_total(
        [m["locked_total_cents"] for m in total_members]
    )
    touch(group)


# ---------------------------------------------------------------------------
# Cancellation release cascade (PRD §3.8)
# ---------------------------------------------------------------------------

def cancel_order(order):
    """Drive an order to CANCELLED and unwind its commitments. Precondition (no
    pickup record) is checked by the caller."""
    prev_status = order["status"]

    # Release active fabric reservations (only if past DRAFT).
    if prev_status in ("CONFIRMED", "IN_FITTING", "REMAKE"):
        fabric = _order_fabric(order)
        if fabric is not None:
            reservations = 1 + order["remake_round"]  # confirm + each remake re-reserve
            fabric["bolt_meters_remaining"] += order["fabric_meters_required"] * reservations
            touch(fabric)

    # All still-SCHEDULED fittings -> FAILED.
    for f in db.fittings.values():
        if f["order_id"] == order["id"] and f["outcome"] == "SCHEDULED":
            f["outcome"] = "FAILED"
            touch(f)

    # All CAPTURED payments -> REFUNDED; refund sum to store credit.
    refunded_sum = 0
    for p in order_payments(order["id"]):
        if p["status"] == "CAPTURED":
            p["status"] = "REFUNDED"
            refunded_sum += p["amount_cents"]
    if refunded_sum > 0:
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += refunded_sum
            touch(customer)

    # Linked measurement profile LOCKED -> SUPERSEDED.
    profile = db.measurement_profiles.get(order["measurement_profile_id"])
    if profile is not None and profile["status"] == "LOCKED":
        profile["status"] = "SUPERSEDED"
        touch(profile)

    order["status"] = "CANCELLED"
    recompute_balance(order)
    touch(order)

    # Group recompute if grouped.
    if order["group_order_id"]:
        group = db.group_orders.get(order["group_order_id"])
        if group is not None:
            recompute_group(group)


def _order_fabric(order):
    """The fabric reserved by this order = the fabric on its first option line."""
    first = first_option_line(order["id"])
    if first is None:
        return None
    return db.fabrics.get(first["fabric_id"])
