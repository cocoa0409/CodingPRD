"""Derived-figure recomputation: the cascades' arithmetic in one place.

A recompute is a mutation only when a stored value actually changes; that is
when the row's `version` advances and `updated_at` is refreshed.
"""

from decimal import Decimal

from core.money import round_half_up
from core.store import DB, ordered, touch_if_changed
from services import pricing

MONEY_LINE_STATES = ("FILLED", "SHORT_FILLED", "SUBSTITUTED")
ESTIMATE_LINE_STATES = ("CONFIRMED", "FILLED", "SHORT_FILLED", "SUBSTITUTED")


# ------------------------------------------------------------- collections --

def lines_of_order(order):
    return ordered([l for l in DB.order_lines.values()
                    if l["member_order_id"] == order["id"]])


def orders_of_drop_run(drop_run):
    return ordered([o for o in DB.member_orders.values()
                    if o["drop_run_id"] == drop_run["id"]])


def drop_runs_of_route_run(route_run):
    return ordered([d for d in DB.drop_runs.values()
                    if d["route_run_id"] == route_run["id"]])


def drop_runs_of_cycle(cycle):
    return ordered([d for d in DB.drop_runs.values() if d["cycle_id"] == cycle["id"]])


def route_runs_of_cycle(cycle):
    return ordered([r for r in DB.route_runs.values() if r["cycle_id"] == cycle["id"]])


def orders_of_route_run(route_run):
    out = []
    for drop_run in drop_runs_of_route_run(route_run):
        out.extend(orders_of_drop_run(drop_run))
    return ordered(out)


def lines_of_route_run(route_run):
    out = []
    for order in orders_of_route_run(route_run):
        out.extend(lines_of_order(order))
    return ordered(out)


# ------------------------------------------------------------- order money --

def order_member(order):
    return DB.get("Member", order["member_id"])


def discount_pct(order):
    member = order_member(order)
    return Decimal(str(member["discount_pct"])) if member else Decimal("0")


def recompute_order_money(order):
    """member_order_totals STEPS 1-4."""
    before = {k: order[k] for k in
              ("gross_cents", "split_fee_cents", "tier_discount_cents",
               "pre_credit_total_cents")}
    gross = 0
    split_fee = 0
    for line in lines_of_order(order):
        if line["status"] in MONEY_LINE_STATES:
            gross += line["allocated_units"] * line["unit_price_cents"]
            split_fee += line["allocated_units"] * line["split_fee_per_unit_cents"]
    order["gross_cents"] = gross
    order["split_fee_cents"] = split_fee
    order["tier_discount_cents"] = round_half_up(Decimal(gross) * discount_pct(order))
    order["pre_credit_total_cents"] = (gross - order["tier_discount_cents"]
                                       + order["freight_alloc_cents"]
                                       + order["reefer_alloc_cents"])
    return touch_if_changed(order, before)


def estimated_total(order):
    """payment_authorization_estimate, first two lines."""
    gross = 0
    for line in lines_of_order(order):
        if line["status"] in ESTIMATE_LINE_STATES:
            gross += line["confirmed_units"] * line["unit_price_cents"]
    discount = round_half_up(Decimal(gross) * discount_pct(order))
    return gross, gross - discount


def recompute_order_estimate(order):
    before = {"estimated_total_cents": order["estimated_total_cents"]}
    _, total = estimated_total(order)
    order["estimated_total_cents"] = total
    return touch_if_changed(order, before)


# ----------------------------------------------------------- drop run math --

def live_drop_subtotal(drop_run):
    """The pre-lock live figure: REQUESTED lines on this drop run's
    non-CANCELLED orders, valued at the prices currently in force."""
    subtotal = 0
    discount = 0
    for order in orders_of_drop_run(drop_run):
        if order["status"] == "CANCELLED":
            continue
        for line in lines_of_order(order):
            if line["status"] != "REQUESTED":
                continue
            item = DB.get("Item", line["item_id"])
            if item is None:
                continue
            subtotal += line["qty_units"] * pricing.live_unit_price(item, line["qty_units"])
        discount += order["tier_discount_cents"]
    return subtotal, subtotal - discount


def locked_drop_subtotal(drop_run):
    """The hop-4 figure: LOCKED orders, CONFIRMED lines, confirmed_units."""
    subtotal = 0
    discount = 0
    for order in orders_of_drop_run(drop_run):
        if order["status"] != "LOCKED":
            continue
        for line in lines_of_order(order):
            if line["status"] == "CONFIRMED":
                subtotal += line["confirmed_units"] * line["unit_price_cents"]
        discount += order["tier_discount_cents"]
    return subtotal, subtotal - discount


def write_drop_subtotal(drop_run, subtotal, discounted):
    before = {"subtotal_cents": drop_run["subtotal_cents"],
              "discounted_subtotal_cents": drop_run["discounted_subtotal_cents"]}
    drop_run["subtotal_cents"] = subtotal
    drop_run["discounted_subtotal_cents"] = discounted
    return touch_if_changed(drop_run, before)


def recompute_live_drop_subtotal(drop_run):
    """Recompute the drop run's live subtotal and propagate to the route run,
    which is maintained live before the lock so a merge is observable."""
    subtotal, discounted = live_drop_subtotal(drop_run)
    changed = write_drop_subtotal(drop_run, subtotal, discounted)
    route_run = DB.get("RouteRun", drop_run["route_run_id"])
    if route_run is not None:
        recompute_route_aggregate(route_run)
    return changed


def recompute_route_aggregate(route_run):
    """route_qualification's sum: DropRuns on this run whose status is OPEN or
    QUALIFIED."""
    before = {"aggregated_subtotal_cents": route_run["aggregated_subtotal_cents"]}
    total = 0
    for drop_run in drop_runs_of_route_run(route_run):
        if drop_run["status"] in ("OPEN", "QUALIFIED"):
            total += drop_run["subtotal_cents"]
    route_run["aggregated_subtotal_cents"] = total
    return touch_if_changed(route_run, before)


# ------------------------------------------------------- received subtotals --

def _received_value(lines):
    total = 0
    for line in lines:
        if line["status"] in MONEY_LINE_STATES:
            total += line["allocated_units"] * line["unit_price_cents"]
    return total


def recompute_drop_received_subtotal(drop_run):
    before = {"received_subtotal_cents": drop_run["received_subtotal_cents"]}
    total = 0
    for order in orders_of_drop_run(drop_run):
        total += _received_value(lines_of_order(order))
    drop_run["received_subtotal_cents"] = total
    return touch_if_changed(drop_run, before)


def recompute_route_received_subtotal(route_run):
    before = {"received_subtotal_cents": route_run["received_subtotal_cents"]}
    route_run["received_subtotal_cents"] = _received_value(lines_of_route_run(route_run))
    return touch_if_changed(route_run, before)


def recompute_drop_reefer_alloc(drop_run):
    before = {"reefer_alloc_cents": drop_run["reefer_alloc_cents"]}
    drop_run["reefer_alloc_cents"] = sum(o["reefer_alloc_cents"]
                                         for o in orders_of_drop_run(drop_run))
    return touch_if_changed(drop_run, before)
