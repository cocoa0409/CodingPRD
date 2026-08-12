"""POST /receipt-lines: the receipt cascade and the shortage allocation."""

from core.money import largest_remainder
from core.store import DB, ordered, touch
from services import recompute, substitution

PARTICIPATING_STATES = ("CONFIRMED", "SHORT_FILLED")
FULFILMENT_LINE_STATES = ("CONFIRMED", "FILLED", "SHORT_FILLED", "SUBSTITUTED", "DROPPED")


def lines_feeding(aggregate):
    """Every order line that fed this (RouteRun, Item) aggregate."""
    route_run = DB.get("RouteRun", aggregate["route_run_id"])
    out = []
    for line in recompute.lines_of_route_run(route_run):
        if line["item_id"] == aggregate["item_id"]:
            out.append(line)
    return ordered(out)


def participants(aggregate):
    return [l for l in lines_feeding(aggregate)
            if l["status"] in PARTICIPATING_STATES and l["confirmed_units"] > 0]


def received_item(aggregate, substitute_item):
    if substitute_item is not None:
        return substitute_item
    return DB.get("Item", aggregate["item_id"])


def allocate(aggregate):
    """shortage_allocation.

    Returns ({line_id: units allocated by this pass},
             {line_id: the status the line held before this pass}).
    """
    lines = participants(aggregate)
    before = {l["id"]: l["allocated_units"] for l in lines}
    before_status = {l["id"]: l["status"] for l in lines}
    total_demand = sum(l["confirmed_units"] for l in lines)
    supply = aggregate["units_received"]

    if not lines:
        return {}, {}

    if supply >= total_demand:
        for line in lines:
            line["allocated_units"] = line["confirmed_units"]
            line["allocation_remainder_rank"] = 0
    else:
        shares, ranked = largest_remainder(supply, [l["confirmed_units"] for l in lines])
        for index, line in enumerate(lines):
            line["allocated_units"] = shares[index]
        for position, index in enumerate(ranked):
            lines[index]["allocation_remainder_rank"] = position + 1

    for line in lines:
        line["short_units"] = line["confirmed_units"] - line["allocated_units"]
        if line["allocated_units"] == line["confirmed_units"]:
            line["status"] = "FILLED"
            line["line_gross_cents"] = line["allocated_units"] * line["unit_price_cents"]
        elif line["allocated_units"] > 0:
            line["status"] = "SHORT_FILLED"
            line["line_gross_cents"] = line["allocated_units"] * line["unit_price_cents"]
        else:
            line["status"] = "DROPPED"
            line["line_gross_cents"] = 0
        touch(line)

    return ({l["id"]: l["allocated_units"] - before[l["id"]] for l in lines},
            before_status)


def settle_orders(lines):
    """Move the affected orders on the fulfilment axis and recompute money."""
    seen = {}
    for line in lines:
        order = DB.get("MemberOrder", line["member_order_id"])
        if order is not None:
            seen[order["id"]] = order
    for order in ordered(list(seen.values())):
        if order["status"] not in ("LOCKED", "FILLED", "SHORT_FILLED"):
            recompute.recompute_order_money(order)
            continue
        short = False
        for line in recompute.lines_of_order(order):
            if line["status"] not in FULFILMENT_LINE_STATES:
                continue
            if line["allocated_units"] < line["confirmed_units"]:
                short = True
                break
        target = "SHORT_FILLED" if short else "FILLED"
        if order["status"] != target:
            order["status"] = target
            touch(order)
        recompute.recompute_order_money(order)
    return list(seen.values())


def refresh_received_subtotals(route_run):
    for drop_run in recompute.drop_runs_of_route_run(route_run):
        recompute.recompute_drop_received_subtotal(drop_run)
    recompute.recompute_route_received_subtotal(route_run)


def record_receipt(route_run, aggregate, cases_received, substitute_item,
                   substitute_case_price_cents, user_id):
    item = received_item(aggregate, substitute_item)
    units = cases_received * item["case_pack_units"]
    receipt = DB.insert("ReceiptLine", {
        "route_run_id": route_run["id"],
        "case_aggregate_id": aggregate["id"],
        "substitute_item_id": substitute_item["id"] if substitute_item else None,
        "cases_received": cases_received,
        "substitute_case_price_cents": substitute_case_price_cents,
        "units_received": units,
        "recorded_by_user_id": user_id,
    })

    aggregate["units_received"] += units
    touch(aggregate)

    deltas, before_status = allocate(aggregate)
    touched_lines = [DB.get("OrderLine", line_id) for line_id in deltas]

    if substitute_item is not None:
        for line in ordered([l for l in touched_lines if deltas[l["id"]] > 0]):
            offer = substitution.create_offer(line, receipt, substitute_item,
                                              deltas[line["id"]],
                                              substitute_case_price_cents)
            substitution.resolve_on_creation(offer, line,
                                             before_status.get(line["id"]))

    settle_orders([l for l in touched_lines if l is not None])
    refresh_received_subtotals(route_run)
    touch(route_run)
    return receipt


def units_for_cases(aggregate, cases_received, substitute_item):
    return cases_received * received_item(aggregate, substitute_item)["case_pack_units"]
