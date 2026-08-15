"""SeasonAllocation ledger: derived-field reconciliation per PRD §3.2.

committed_af     = sum requested_quantity_af over orders in {REQUESTED, SCHEDULED, FLOWING}
delivered_af     = sum measured volumes over this allocation's DELIVERED orders
transfers_in/out = sum quantity_af over POSTED TransferRequests for this account+season
available_af     = effective + carryover_in + transfers_in - transfers_out - delivered - committed
over_allocated   = max(0, delivered - (effective + carryover_in + transfers_in - transfers_out))
effective        = curtailed_entitlement_af while CURTAILED, else base_entitlement_af
"""
from decimal import Decimal

import db
from db import store, D

ZERO = Decimal("0")


def find_allocation(account_id, season_id):
    for a in store.allocations.values():
        if a["water_account_id"] == account_id and a["season_id"] == season_id:
            return a
    return None


def allocations_of_season(season_id):
    return [a for a in store.allocations.values() if a["season_id"] == season_id]


def orders_of_allocation(alloc):
    return [o for o in store.turnout_orders.values()
            if o["season_allocation_id"] == alloc["id"]]


def orders_of_season(season_id):
    alloc_ids = {a["id"] for a in allocations_of_season(season_id)}
    return [o for o in store.turnout_orders.values()
            if o["season_allocation_id"] in alloc_ids]


def season_of_allocation(alloc):
    return store.seasons.get(alloc["season_id"])


def entitlement_pool(alloc):
    """effective + carryover_in + transfers_in - transfers_out (no deliveries netted)."""
    return (D(alloc["effective_entitlement_af"]) + D(alloc["carryover_in_af"])
            + D(alloc["transfers_in_af"]) - D(alloc["transfers_out_af"]))


def recompute_allocation(alloc):
    committed = ZERO
    delivered = ZERO
    for o in orders_of_allocation(alloc):
        if o["status"] in ("REQUESTED", "SCHEDULED", "FLOWING"):
            committed += D(o["requested_quantity_af"])
        if o["status"] == "DELIVERED" and o["actual_delivered_af"] is not None:
            delivered += D(o["actual_delivered_af"])
    transfers_in = ZERO
    transfers_out = ZERO
    for t in store.transfer_requests.values():
        if t["season_id"] != alloc["season_id"] or t["status"] != "POSTED":
            continue
        if t["to_account_id"] == alloc["water_account_id"]:
            transfers_in += D(t["quantity_af"])
        if t["from_account_id"] == alloc["water_account_id"]:
            transfers_out += D(t["quantity_af"])
    if alloc["status"] == "CURTAILED" and alloc["curtailed_entitlement_af"] is not None:
        effective = D(alloc["curtailed_entitlement_af"])
    else:
        effective = D(alloc["base_entitlement_af"])
    alloc["effective_entitlement_af"] = effective
    alloc["committed_af"] = committed
    alloc["delivered_af"] = delivered
    alloc["transfers_in_af"] = transfers_in
    alloc["transfers_out_af"] = transfers_out
    pool = effective + D(alloc["carryover_in_af"]) + transfers_in - transfers_out
    alloc["available_af"] = pool - delivered - committed
    alloc["over_allocated_af"] = max(ZERO, delivered - pool)
    return alloc


def refresh_allocation(alloc, bump=True):
    """Recompute derived ledger fields; optionally record the mutation."""
    recompute_allocation(alloc)
    if bump:
        db.touch(alloc)
    return alloc
