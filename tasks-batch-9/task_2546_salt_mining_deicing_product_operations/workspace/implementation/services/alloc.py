"""Shared allocation mechanics: the waterfall pool, reservation and release."""

import db
from db import store, touch
from services import calc, derive
from util import D, ZERO, q2

ADMISSIBLE_DEPOT_STATES = {
    "ROUTINE": ("OPEN",),
    "STORM_EMERGENCY": ("OPEN", "SURGE"),
}


def new_allocation(order, lot, tons, origin, rank_position):
    alloc = db.stamp()
    alloc.update({
        "delivery_order_id": order["id"],
        "stockpile_lot_id": lot["id"],
        "tons": q2(tons),
        "origin": origin,
        "rank_position": rank_position,
        "state": "RESERVED",
    })
    store.allocations[alloc["id"]] = alloc
    touch(lot)
    return alloc


def candidate_lots(order, contract):
    """Eligible lots for the waterfall, already in rank order."""
    admissible = ADMISSIBLE_DEPOT_STATES[order["storm_priority"]]
    pool = []
    for lot in store.lots.values():
        if lot["lot_state"] != "AVAILABLE":
            continue
        if lot["product_line"] != contract["product_line"]:
            continue
        if derive.lot_available_tons(lot) <= ZERO:
            continue
        depot = store.depots.get(lot["depot_id"])
        if depot is None:
            continue
        if depot["state_code"] != contract["state_code"]:
            continue
        if depot["depot_state"] not in admissible:
            continue
        pool.append((lot, depot))

    def rank_key(entry):
        lot, depot = entry
        local = 0 if depot["id"] == order["depot_id"] else 1
        return (
            local,
            D(depot["outbound_freight_rate_per_ton"]),
            -derive.lot_available_tons(lot),
            lot["created_at"],
            lot["_seq"],
        )

    pool.sort(key=rank_key)
    return pool


def release_allocation(alloc):
    lot = derive.get_lot(alloc["stockpile_lot_id"])
    alloc["state"] = "RELEASED"
    touch(alloc)
    touch(lot)
    return lot


def consume_allocation(alloc):
    lot = derive.get_lot(alloc["stockpile_lot_id"])
    alloc["state"] = "CONSUMED"
    lot["tons_on_hand"] = q2(D(lot["tons_on_hand"]) - D(alloc["tons"]))
    if (D(lot["tons_on_hand"]) == ZERO
            and derive.lot_reserved_tons(lot["id"]) == ZERO
            and lot["lot_state"] == "AVAILABLE"):
        lot["lot_state"] = "DEPLETED"
    touch(alloc)
    touch(lot)
    return lot


def accrue_shortfall(order, contract, allocated):
    """Hop 1 of the per-event penalty cascade; hops 2 and 3 are derived."""
    order["shorted_tons"] = q2(D(order["requested_tons"]) - D(allocated))
    order["shortfall_penalty_usd"] = calc.order_shortfall_penalty(
        order, contract, allocated_tons=allocated)
    order["penalty_state"] = "ACCRUED"
    touch(contract)


def clear_shortfall(order, contract):
    order["shorted_tons"] = ZERO
    order["shortfall_penalty_usd"] = q2(ZERO)
    order["penalty_state"] = "NONE"
    touch(contract)
