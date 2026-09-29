"""Derived / computed field maintenance and entity lookups."""

import db
from db import store, touch
from errors import (
    ERR_ALLOCATION_NOT_FOUND,
    ERR_BATCH_NOT_FOUND,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DEPOT_NOT_FOUND,
    ERR_FORECAST_NOT_FOUND,
    ERR_INSPECTION_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_MINE_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PANEL_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    fail,
)
from services import calc
from util import D, q2, ZERO

# ------------------------------------------------------------------ lookups

def _lookup(table, entity_id, error_id, label):
    if not isinstance(entity_id, str) or entity_id not in table:
        fail(error_id, "%s %s was not found" % (label, entity_id))
    return table[entity_id]


def get_mine(mine_id):
    return _lookup(store.mines, mine_id, ERR_MINE_NOT_FOUND, "mine")


def get_panel(panel_id):
    return _lookup(store.panels, panel_id, ERR_PANEL_NOT_FOUND, "panel")


def get_inspection(inspection_id):
    return _lookup(store.inspections, inspection_id, ERR_INSPECTION_NOT_FOUND,
                   "inspection")


def get_run(run_id):
    return _lookup(store.runs, run_id, ERR_RUN_NOT_FOUND, "production run")


def get_batch(batch_id):
    return _lookup(store.batches, batch_id, ERR_BATCH_NOT_FOUND,
                   "treatment batch")


def get_depot(depot_id):
    return _lookup(store.depots, depot_id, ERR_DEPOT_NOT_FOUND, "depot")


def get_lot(lot_id):
    return _lookup(store.lots, lot_id, ERR_LOT_NOT_FOUND, "stockpile lot")


def get_shipment(shipment_id):
    return _lookup(store.shipments, shipment_id, ERR_SHIPMENT_NOT_FOUND,
                   "shipment")


def get_forecast(forecast_id):
    return _lookup(store.forecasts, forecast_id, ERR_FORECAST_NOT_FOUND,
                   "season forecast")


def get_contract(contract_id):
    return _lookup(store.contracts, contract_id, ERR_CONTRACT_NOT_FOUND,
                   "bid contract")


def get_order(order_id):
    return _lookup(store.orders, order_id, ERR_ORDER_NOT_FOUND,
                   "delivery order")


def get_allocation(allocation_id):
    return _lookup(store.allocations, allocation_id, ERR_ALLOCATION_NOT_FOUND,
                   "allocation")


# ------------------------------------------------------------- collections

def panels_of_mine(mine_id):
    return [p for p in store.panels.values() if p["mine_id"] == mine_id]


def runs_of_mine(mine_id):
    return [r for r in store.runs.values() if r["mine_id"] == mine_id]


def runs_of_panel(panel_id):
    return [r for r in store.runs.values() if r["panel_id"] == panel_id]


def scheduled_runs_of_mine(mine_id):
    return [r for r in store.runs.values()
            if r["mine_id"] == mine_id and r["status"] == "SCHEDULED"]


def batches_of_run(run_id):
    return [b for b in store.batches.values() if b["production_run_id"] == run_id]


def lots_of_depot(depot_id):
    return [l for l in store.lots.values() if l["depot_id"] == depot_id]


def allocations_of_order(order_id):
    return [a for a in store.allocations.values()
            if a["delivery_order_id"] == order_id]


def allocations_of_lot(lot_id):
    return [a for a in store.allocations.values()
            if a["stockpile_lot_id"] == lot_id]


def orders_of_contract(contract_id):
    return [o for o in store.orders.values()
            if o["bid_contract_id"] == contract_id]


def inspections_of_panel(panel_id):
    return [i for i in store.inspections.values() if i["panel_id"] == panel_id]


# ----------------------------------------------------------------- mine

def mine_scheduled_hoist_tons_open(mine_id):
    total = ZERO
    for run in scheduled_runs_of_mine(mine_id):
        total += D(run["planned_tons"])
    return q2(total)


def mine_producing_panel_count(mine_id):
    return len([p for p in panels_of_mine(mine_id) if p["status"] == "PRODUCING"])


def refresh_mine_capacity(mine):
    mine["effective_hoist_tons_per_day"] = calc.mine_effective_hoist(mine)


# ----------------------------------------------------------------- panel

def panel_defect_count(panel_id):
    return len([i for i in inspections_of_panel(panel_id)
                if i["finding"] == "DEFECT"])


def panel_mined_tons(panel_id):
    total = ZERO
    for run in runs_of_panel(panel_id):
        if run["status"] in ("HOISTED", "CLOSED"):
            total += D(run["hoisted_tons"])
    return q2(total)


PANEL_LIVE_STATUSES = ("PLANNED", "DEVELOPED", "PRODUCING", "SUSPENDED")


def recompute_panel_reserves(mine):
    """Every non-terminal panel is repriced; a recomputation counts as a mutation."""
    for panel in db.by_seq(panels_of_mine(mine["id"])):
        if panel["status"] not in PANEL_LIVE_STATUSES:
            continue
        panel["recoverable_tons"] = calc.panel_recoverable_tons(panel, mine)
        touch(panel)


# ------------------------------------------------------------------- run

def run_open_batch_count(run_id):
    return len([b for b in batches_of_run(run_id) if b["qc_state"] == "PENDING"])


# ----------------------------------------------------------------- depot

OCCUPYING_LOT_STATES = ("AVAILABLE", "QUARANTINED")


def depot_stored_tons(depot_id, storage_kind):
    total = ZERO
    for lot in lots_of_depot(depot_id):
        if lot["storage_kind"] == storage_kind and lot["lot_state"] in OCCUPYING_LOT_STATES:
            total += D(lot["tons_on_hand"])
    return q2(total)


def depot_covered_stored(depot_id):
    return depot_stored_tons(depot_id, "COVERED")


def depot_open_pad_stored(depot_id):
    return depot_stored_tons(depot_id, "OPEN_PAD")


def depot_utilization_pct(depot):
    capacity = D(depot["covered_capacity_tons"])
    if capacity == ZERO:
        return q2(ZERO)
    return q2(depot_covered_stored(depot["id"]) * D(100) / capacity)


def depot_reserved_tons(depot_id):
    total = ZERO
    for lot in lots_of_depot(depot_id):
        total += lot_reserved_tons(lot["id"])
    return q2(total)


def maybe_auto_surge(depot):
    """OPEN -> SURGE when covered occupancy reaches 90% of covered capacity."""
    if depot["depot_state"] != "OPEN":
        return False
    capacity = D(depot["covered_capacity_tons"])
    if capacity <= ZERO:
        return False
    stored = depot_covered_stored(depot["id"])
    if stored * D(100) >= capacity * calc.AUTO_SURGE_THRESHOLD_PCT:
        depot["depot_state"] = "SURGE"
        return True
    return False


# ------------------------------------------------------------------- lot

def lot_reserved_tons(lot_id):
    total = ZERO
    for alloc in allocations_of_lot(lot_id):
        if alloc["state"] == "RESERVED":
            total += D(alloc["tons"])
    return q2(total)


def lot_available_tons(lot):
    return q2(D(lot["tons_on_hand"]) - lot_reserved_tons(lot["id"]))


# ------------------------------------------------------------------ order

def order_allocated_tons(order_id):
    total = ZERO
    for alloc in allocations_of_order(order_id):
        if alloc["state"] in ("RESERVED", "CONSUMED"):
            total += D(alloc["tons"])
    return q2(total)


# --------------------------------------------------------------- contract

def contract_fulfilled_tons(contract_id):
    total = ZERO
    for order in orders_of_contract(contract_id):
        if order["status"] == "DELIVERED":
            total += order_allocated_tons(order["id"])
    return q2(total)


def contract_open_committed_tons(contract, fulfilled=None):
    if fulfilled is None:
        fulfilled = contract_fulfilled_tons(contract["id"])
    remaining = D(contract["committed_tons"]) - D(fulfilled)
    if remaining < ZERO:
        remaining = ZERO
    return q2(remaining)


def contract_take_pct(contract, fulfilled=None):
    if fulfilled is None:
        fulfilled = contract_fulfilled_tons(contract["id"])
    committed = D(contract["committed_tons"])
    if committed == ZERO:
        return q2(ZERO)
    return q2(D(fulfilled) * D(100) / committed)


def contract_penalty_accrued(contract_id):
    total = ZERO
    for order in orders_of_contract(contract_id):
        if order["penalty_state"] == "ACCRUED" and order.get("shortfall_penalty_usd") is not None:
            total += D(order["shortfall_penalty_usd"])
    return q2(total)


def contract_accrued_order_count(contract_id):
    return len([o for o in orders_of_contract(contract_id)
                if o["penalty_state"] == "ACCRUED"])


def contract_breach_watch(contract, penalty_accrued=None):
    value = contract.get("contract_value_usd")
    if value is None:
        return False
    if penalty_accrued is None:
        penalty_accrued = contract_penalty_accrued(contract["id"])
    return D(penalty_accrued) >= D("0.05") * D(value)


def contract_cumulative_shorted(contract_id):
    total = ZERO
    for order in orders_of_contract(contract_id):
        if order["penalty_state"] == "ACCRUED" and order.get("shorted_tons") is not None:
            total += D(order["shorted_tons"])
    return q2(total)


def contract_supply_reliability(contract):
    committed = D(contract["committed_tons"])
    cumulative = contract_cumulative_shorted(contract["id"])
    if committed == ZERO:
        haircut = ZERO
    else:
        haircut = q2(cumulative * D(100) / committed)
    if haircut > D(40):
        haircut = D(40)
    forfeit = D(25) if contract["status"] == "FORFEITED" else ZERO
    score = D(100) - haircut - forfeit
    if score < ZERO:
        score = ZERO
    if score > D(100):
        score = D(100)
    return q2(score)


TAKE_BAND_STATUSES = ("REQUESTED", "ALLOCATED", "SHORTED", "DELIVERED")


def contract_take_band_consumed(contract_id):
    total = ZERO
    for order in orders_of_contract(contract_id):
        if order["status"] in TAKE_BAND_STATUSES:
            total += D(order["requested_tons"])
    return q2(total)


def contract_take_band_limit(contract):
    return q2(D(contract["committed_tons"]) * D(contract["max_take_pct"]) / D(100))


def contract_preseason_required(contract):
    return q2(D(contract["committed_tons"]) * D(contract["min_take_pct"]) / D(100))


def contract_preseason_coverage(contract):
    total = ZERO
    for lot in store.lots.values():
        if lot["lot_state"] != "AVAILABLE":
            continue
        if lot["product_line"] != contract["product_line"]:
            continue
        depot = store.depots.get(lot["depot_id"])
        if depot is None:
            continue
        if depot["state_code"] != contract["state_code"]:
            continue
        if depot["depot_state"] not in ("OPEN", "SURGE"):
            continue
        total += lot_available_tons(lot)
    return q2(total)
