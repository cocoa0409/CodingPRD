"""POST /cycles/{cycle_id}/lock — the six-hop aggregation cascade (PRD §3.4)."""

from core import clock
from core.errors import ApiError
from core.store import DB, ordered, touch
from services import pricing, recompute


def orders_of_cycle(cycle):
    out = []
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        out.extend(recompute.orders_of_drop_run(drop_run))
    return ordered(out)


def cancel_lines(order, from_states):
    for line in recompute.lines_of_order(order):
        if line["status"] in from_states:
            line["status"] = "CANCELLED"
            touch(line)


def run_lock(cycle):
    cutoff = clock.parse(cycle["cutoff_at"])

    # Atomicity: no line may confirm without a bound price, so the whole request
    # is refused before any hop mutates anything.
    for order in orders_of_cycle(cycle):
        if order["status"] != "SUBMITTED":
            continue
        for line in recompute.lines_of_order(order):
            if line["status"] != "REQUESTED":
                continue
            if pricing.bound_price_version(line["item_id"], cutoff) is None:
                raise ApiError("ERR_NO_EFFECTIVE_PRICE")

    cycle["status"] = "LOCKED"
    cycle["locked_at"] = clock.now_iso()

    locked_orders = _hop1(cycle)
    _hop2(locked_orders, cutoff)
    _hop3(cycle)
    _hop4(cycle)
    deferred_runs = _hop5(cycle)
    _hop6(deferred_runs)

    touch(cycle)
    return cycle


def _hop1(cycle):
    """Orders settle: DRAFT cancels, SUBMITTED locks."""
    locked = []
    for order in orders_of_cycle(cycle):
        if order["status"] == "DRAFT":
            order["status"] = "CANCELLED"
            touch(order)
            cancel_lines(order, ("REQUESTED",))
        elif order["status"] == "SUBMITTED":
            order["status"] = "LOCKED"
            touch(order)
            locked.append(order)
    return locked


def _hop2(locked_orders, cutoff):
    """Lines confirm and prices bind at the cycle's cutoff_at."""
    for order in locked_orders:
        for line in recompute.lines_of_order(order):
            if line["status"] != "REQUESTED":
                continue
            item = DB.get("Item", line["item_id"])
            bound = pricing.bound_price_version(line["item_id"], cutoff)
            base, is_split, fee, unit_price = pricing.split_unit_price(
                bound["case_price_cents"], item["case_pack_units"], line["qty_units"])
            line["status"] = "CONFIRMED"
            line["bound_case_price_cents"] = bound["case_price_cents"]
            line["unit_price_cents"] = unit_price
            line["is_split_unit"] = is_split
            line["split_fee_per_unit_cents"] = fee
            line["confirmed_units"] = line["qty_units"]
            touch(line)


def _hop3(cycle):
    """One CaseAggregate per (RouteRun, Item), written in Item.sku ASC order."""
    pairs = {}
    for route_run in recompute.route_runs_of_cycle(cycle):
        for drop_run in recompute.drop_runs_of_route_run(route_run):
            if drop_run["status"] != "OPEN":
                continue
            for order in recompute.orders_of_drop_run(drop_run):
                for line in recompute.lines_of_order(order):
                    if line["status"] != "CONFIRMED":
                        continue
                    pairs.setdefault((route_run["id"], line["item_id"]), []).append(line)

    def sort_key(entry):
        (route_run_id, item_id) = entry
        item = DB.get("Item", item_id)
        route_run = DB.get("RouteRun", route_run_id)
        return (item["sku"], route_run["created_at"], route_run["_seq"])

    for key in sorted(pairs.keys(), key=sort_key):
        route_run_id, item_id = key
        _build_aggregate(route_run_id, item_id, ordered(pairs[key]), cycle)


def _build_aggregate(route_run_id, item_id, lines, cycle):
    item = DB.get("Item", item_id)
    pack = item["case_pack_units"]
    requested_units = sum(l["qty_units"] for l in lines)
    full_cases = requested_units // pack
    remainder_units = requested_units % pack
    policy = item["remainder_policy"]
    overage_units = 0
    dropped_units = 0
    overage_line_id = None
    cases_ordered = full_cases

    if remainder_units != 0:
        if policy == "ROUND_UP":
            cases_ordered = full_cases + 1
            overage_units = pack - remainder_units
            # charged whole to the line with the greatest qty_units, ties by
            # the earlier created_at
            overage_line = sorted(
                lines, key=lambda l: (-l["qty_units"], l["created_at"], l["_seq"]))[0]
            overage_line["confirmed_units"] = overage_line["qty_units"] + overage_units
            touch(overage_line)
            overage_line_id = overage_line["id"]
        elif policy == "DROP":
            dropped_units = remainder_units
            shortfall = remainder_units
            for line in sorted(lines, key=lambda l: (l["created_at"], l["_seq"]),
                               reverse=True):
                take = min(line["qty_units"], shortfall)
                line["confirmed_units"] = line["qty_units"] - take
                shortfall -= take
                if line["confirmed_units"] == 0:
                    line["status"] = "DROPPED"
                    line["line_gross_cents"] = 0
                touch(line)
                if shortfall == 0:
                    break

    bound = pricing.bound_price_version(item_id, clock.parse(cycle["cutoff_at"]))
    DB.insert("CaseAggregate", {
        "route_run_id": route_run_id,
        "item_id": item_id,
        "overage_order_line_id": overage_line_id,
        "requested_units": requested_units,
        "cases_ordered": cases_ordered,
        "covered_units": cases_ordered * pack,
        "remainder_units": remainder_units,
        "overage_units": overage_units,
        "dropped_units": dropped_units,
        "policy_applied": policy,
        "case_price_cents": bound["case_price_cents"] if bound else 0,
        "units_received": 0,
    })


def _hop4(cycle):
    """Drops qualify against their drop minimum (INCLUSIVE)."""
    for order in orders_of_cycle(cycle):
        recompute.recompute_order_estimate(order)
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        subtotal, discounted = recompute.locked_drop_subtotal(drop_run)
        recompute.write_drop_subtotal(drop_run, subtotal, discounted)
    for drop_run in recompute.drop_runs_of_cycle(cycle):
        if drop_run["status"] != "OPEN":
            continue
        drop_point = DB.get("DropPoint", drop_run["drop_point_id"])
        if drop_run["subtotal_cents"] >= drop_point["drop_minimum_cents"]:
            drop_run["status"] = "QUALIFIED"
            touch(drop_run)
        else:
            drop_run["status"] = "DEFERRED"
            touch(drop_run)
            _cancel_drop_orders(drop_run)


def _cancel_drop_orders(drop_run):
    for order in recompute.orders_of_drop_run(drop_run):
        if order["status"] == "LOCKED":
            order["status"] = "CANCELLED"
            touch(order)
            cancel_lines(order, ("CONFIRMED",))


def _hop5(cycle):
    """Routes qualify against their route minimum (STRICTLY GREATER)."""
    deferred = []
    for route_run in recompute.route_runs_of_cycle(cycle):
        recompute.recompute_route_aggregate(route_run)
        if route_run["status"] != "PLANNED":
            continue
        route = DB.get("Route", route_run["route_id"])
        if route_run["aggregated_subtotal_cents"] > route["route_minimum_cents"]:
            route_run["status"] = "QUALIFIED"
        else:
            route_run["status"] = "DEFERRED"
            deferred.append(route_run)
        touch(route_run)
    return deferred


def _hop6(deferred_runs):
    """A deferred route reaches back down and reverts its qualified drops."""
    for route_run in deferred_runs:
        for drop_run in recompute.drop_runs_of_route_run(route_run):
            if drop_run["status"] != "QUALIFIED":
                continue
            drop_run["status"] = "DEFERRED"
            touch(drop_run)
            _cancel_drop_orders(drop_run)
