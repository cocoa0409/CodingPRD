"""Allocation cycles, channel orders and allocation lines (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import calc
import ledger
from calc import D0_2, q2
from db import new_row, ordered, store, touch
from errors import fail
from middleware import actor, authenticate, require_order_owned
from refs import (apply_filters, get_cycle, get_line, get_lot, get_order, get_plant,
                  get_product_line)
from response import created_response, list_response, object_response
from validate import body, dec_field, instant_field, int_field, present, str_field

bp = Blueprint("channel", __name__)

READ_ROLES = ("CorporateOps", "ChannelManager", "ChannelBuyer")
SELLABLE = ("CERTIFIED", "DERATED")
OPEN_ORDER_STATUSES = ("SUBMITTED", "PARTIAL", "BACKORDERED")


def _order_sort_key(order):
    return (calc.TIER_RANK.get(order["priority_tier"], 99),
            order["_required_by_dt"],
            order["created_at"],
            order["_seq"])


def _remaining(order):
    return Decimal(order["requested_sqft"]) - Decimal(order["allocated_sqft"])


# ---------------------------------------------------------------------------
# AllocationCycle
# ---------------------------------------------------------------------------

@bp.post("/allocation-cycles")
def open_cycle():
    authenticate(("ChannelManager",))
    payload = body()
    start_raw, start_dt = instant_field(payload, "period_start")
    end_raw, end_dt = instant_field(payload, "period_end")
    if not end_dt > start_dt:
        fail("ERR_INVALID_REQUEST", "period_end must be strictly later than period_start")
    basis = str_field(payload, "allocation_basis", allowed=("CONTRACT_FIRST", "PRO_RATA"))

    if not present(payload, "plant_id"):
        fail("ERR_INVALID_REQUEST", "plant_id is required")
    plant = get_plant(payload["plant_id"])
    if not present(payload, "product_line_id"):
        fail("ERR_INVALID_REQUEST", "product_line_id is required")
    product_line = get_product_line(payload["product_line_id"])

    row = new_row()
    row.update({
        "plant_id": plant["id"],
        "product_line_id": product_line["id"],
        "period_start": start_raw,
        "period_end": end_raw,
        "_period_start_dt": start_dt,
        "_period_end_dt": end_dt,
        "allocation_basis": basis,
        "peak_season": None,
        "total_available_sqft": None,
        "seasonal_reserve_sqft": None,
        "allocatable_sqft": None,
        "total_requested_sqft": None,
        "shortage_ratio": None,
        "allocated_sqft": D0_2,
        "unallocated_sqft": None,
        "status": "OPEN",
        "_demand_order_ids": [],
    })
    store.cycles[row["id"]] = row
    return created_response(row)


@bp.get("/allocation-cycles/<cycle_id>")
def read_cycle(cycle_id):
    authenticate(READ_ROLES)
    return object_response(get_cycle(cycle_id))


@bp.get("/allocation-cycles")
def list_cycles():
    authenticate(READ_ROLES)
    rows = apply_filters(store.cycles.values(), {
        "plant_id": ("plant_id", "str"),
        "product_line_id": ("product_line_id", "str"),
        "allocation_basis": ("allocation_basis", "str"),
        "peak_season": ("peak_season", "bool"),
        "status": ("status", "str"),
    })
    return list_response(rows)


def _supply_lots(cycle):
    lots = [l for l in store.lots.values()
            if l["plant_id"] == cycle["plant_id"]
            and l["product_line_id"] == cycle["product_line_id"]
            and l["status"] == "AVAILABLE"]
    return ordered(lots)


def _demand_orders(cycle):
    demand = []
    for order in store.orders.values():
        if order["product_line_id"] != cycle["product_line_id"]:
            continue
        if order["status"] not in OPEN_ORDER_STATUSES:
            continue
        if order["_required_by_dt"] > cycle["_period_end_dt"]:
            continue
        if _remaining(order) <= 0:
            continue
        demand.append(order)
    demand.sort(key=_order_sort_key)
    return demand


def _contract_first(demand, allocatable, bag_sqft):
    pool = Decimal(allocatable)
    grants = []
    for order in demand:
        wanted = _remaining(order)
        if wanted > pool:
            wanted = pool
        bags, grant = calc.whole_bag_grant(wanted, bag_sqft)
        pool = pool - Decimal(grant)
        grants.append(Decimal(grant))
    return grants


def _pro_rata(demand, allocatable, shortage, bag_sqft):
    bag = Decimal(bag_sqft)
    grants = []
    for order in demand:
        share = _remaining(order) * Decimal(shortage)
        _bags, grant = calc.whole_bag_grant(share, bag_sqft)
        grants.append(Decimal(grant))
    pool = Decimal(allocatable) - sum(grants, Decimal(0))
    while pool >= bag:
        handed = False
        for index, order in enumerate(demand):
            if pool < bag:
                break
            if grants[index] + bag > _remaining(order):
                continue
            grants[index] = q2(grants[index] + bag)
            pool = pool - bag
            handed = True
        if not handed:
            break
    return grants


def _cut_lines(cycle, demand, grants, lots, bag_sqft):
    bag = Decimal(bag_sqft)
    remaining_by_lot = [(lot, Decimal(lot["available_sqft"])) for lot in lots]
    index = 0
    for order, grant in zip(demand, grants):
        outstanding = Decimal(grant)
        while outstanding > 0 and index < len(remaining_by_lot):
            lot, left = remaining_by_lot[index]
            if left <= 0:
                index += 1
                continue
            take = outstanding if outstanding <= left else left
            line = new_row()
            line.update({
                "allocation_cycle_id": cycle["id"],
                "channel_order_id": order["id"],
                "inventory_lot_id": lot["id"],
                "allocated_sqft": q2(take),
                "bags": int(take / bag),
                "status": "PROPOSED",
                "revoke_reason": None,
            })
            store.lines[line["id"]] = line
            outstanding = outstanding - take
            remaining_by_lot[index] = (lot, left - take)


@bp.post("/allocation-cycles/<cycle_id>/propose")
def propose_cycle(cycle_id):
    authenticate(("ChannelManager",))
    cycle = get_cycle(cycle_id)
    if cycle["status"] not in ("OPEN", "PROPOSED"):
        fail("ERR_INVALID_STATE", "only an OPEN or PROPOSED cycle may be proposed")
    product_line = store.product_lines[cycle["product_line_id"]]
    if product_line["certification_status"] not in SELLABLE:
        fail("ERR_PRODUCT_LINE_NOT_CERTIFIED", "the SKU is not sellable")

    lots = _supply_lots(cycle)
    total_available = q2(sum((Decimal(l["available_sqft"]) for l in lots), Decimal(0)))
    peak = calc.is_peak_season(cycle["_period_start_dt"])
    reserve = calc.seasonal_reserve(total_available, peak)
    allocatable = q2(Decimal(total_available) - Decimal(reserve))
    if not allocatable > 0:
        fail("ERR_NO_ALLOCATABLE_SUPPLY", "no allocatable coverage remains after the reserve")
    demand = _demand_orders(cycle)
    if not demand:
        fail("ERR_NO_ELIGIBLE_ORDERS", "no eligible orders fall inside the demand period")

    bag_sqft = product_line["bag_sqft"]
    total_requested = q2(sum((_remaining(o) for o in demand), Decimal(0)))
    shortage = calc.shortage_ratio(allocatable, total_requested)
    if cycle["allocation_basis"] == "CONTRACT_FIRST":
        grants = _contract_first(demand, allocatable, bag_sqft)
    else:
        grants = _pro_rata(demand, allocatable, shortage, bag_sqft)

    stale = [l for l in ledger.cycle_lines(cycle["id"]) if l["status"] == "PROPOSED"]
    if stale:
        ledger.revoke_lines(stale, "CYCLE_CANCELLED", skip_cycle_ids=(cycle["id"],))

    _cut_lines(cycle, demand, grants, lots, bag_sqft)

    allocated = q2(sum(grants, Decimal(0)))
    cycle["peak_season"] = peak
    cycle["total_available_sqft"] = total_available
    cycle["seasonal_reserve_sqft"] = reserve
    cycle["allocatable_sqft"] = allocatable
    cycle["total_requested_sqft"] = total_requested
    cycle["shortage_ratio"] = shortage
    cycle["allocated_sqft"] = allocated
    cycle["unallocated_sqft"] = q2(Decimal(allocatable) - allocated)
    cycle["status"] = "PROPOSED"
    cycle["_demand_order_ids"] = [o["id"] for o in demand]
    touch(cycle)
    return object_response(cycle)


@bp.post("/allocation-cycles/<cycle_id>/commit")
def commit_cycle(cycle_id):
    authenticate(("ChannelManager",))
    cycle = get_cycle(cycle_id)
    if cycle["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "only a PROPOSED cycle may be committed")
    plant = store.plants[cycle["plant_id"]]
    if plant["melt_posture"] == "FROZEN":
        fail("ERR_MELT_POSTURE_FROZEN", "the plant's melt shop is frozen")

    lines = [l for l in ledger.cycle_lines(cycle["id"]) if l["status"] == "PROPOSED"]
    lot_ids = []
    for line in lines:
        if line["inventory_lot_id"] not in lot_ids:
            lot_ids.append(line["inventory_lot_id"])
    for lot_id in lot_ids:
        lot = store.lots.get(lot_id)
        if lot is not None and lot["status"] == "QUARANTINED":
            fail("ERR_LOT_QUARANTINED", "lot %s is quarantined" % lot_id)

    order_ids = list(cycle.get("_demand_order_ids") or [])
    for line in lines:
        line["status"] = "ALLOCATED"
        touch(line)
        if line["channel_order_id"] not in order_ids:
            order_ids.append(line["channel_order_id"])
    for lot_id in lot_ids:
        lot = store.lots.get(lot_id)
        if lot is not None:
            ledger.recompute_lot(lot)
    for order_id in order_ids:
        order = store.orders.get(order_id)
        if order is not None:
            ledger.recompute_order(order, derive_backorder=True)

    cycle["status"] = "COMMITTED"
    ledger.recompute_cycle(cycle, bump=False)
    touch(cycle)
    return object_response(cycle)


@bp.post("/allocation-cycles/<cycle_id>/cancel")
def cancel_cycle(cycle_id):
    authenticate(("ChannelManager",))
    cycle = get_cycle(cycle_id)
    payload = body()
    reason = str_field(payload, "cancel_reason", required=False, default=None)
    if cycle["status"] not in ("OPEN", "PROPOSED"):
        fail("ERR_INVALID_STATE", "only an OPEN or PROPOSED cycle may be cancelled")
    ledger.cancel_cycle(cycle, reason=reason)
    return object_response(cycle)


# ---------------------------------------------------------------------------
# ChannelOrder
# ---------------------------------------------------------------------------

@bp.post("/channel-orders")
def place_order():
    authenticate(("ChannelBuyer", "ChannelManager"))
    payload = body()
    channel_type = str_field(payload, "channel_type", allowed=("DISTRIBUTOR", "RETAIL"))
    tier = str_field(payload, "priority_tier", allowed=("CONTRACT", "PROGRAM", "SPOT"))
    requested = dec_field(payload, "requested_sqft", gt=0)
    required_raw, required_dt = instant_field(payload, "required_by")

    if not present(payload, "product_line_id"):
        fail("ERR_INVALID_REQUEST", "product_line_id is required")
    product_line = get_product_line(payload["product_line_id"])
    if product_line["certification_status"] not in SELLABLE:
        fail("ERR_PRODUCT_LINE_NOT_CERTIFIED", "the SKU is not sellable")

    row = new_row()
    row.update({
        "product_line_id": product_line["id"],
        "channel_type": channel_type,
        "priority_tier": tier,
        "requested_sqft": q2(requested),
        "required_by": required_raw,
        "_required_by_dt": required_dt,
        "placed_by_user_id": actor(),
        "allocated_sqft": D0_2,
        "fill_rate_pct": D0_2,
        "status": "SUBMITTED",
    })
    store.orders[row["id"]] = row
    return created_response(row)


@bp.get("/channel-orders/<order_id>")
def read_order(order_id):
    authenticate(READ_ROLES)
    return object_response(get_order(order_id))


@bp.get("/channel-orders")
def list_orders():
    authenticate(READ_ROLES)
    rows = apply_filters(store.orders.values(), {
        "product_line_id": ("product_line_id", "str"),
        "channel_type": ("channel_type", "str"),
        "priority_tier": ("priority_tier", "str"),
        "status": ("status", "str"),
    })
    return list_response(rows)


@bp.post("/channel-orders/<order_id>/cancel")
def cancel_order(order_id):
    authenticate(("ChannelBuyer",))
    order = get_order(order_id)
    require_order_owned(order)
    payload = body()
    reason = str_field(payload, "cancel_reason", required=False, default=None)
    if order["status"] not in OPEN_ORDER_STATUSES:
        fail("ERR_INVALID_STATE", "only an open order may be cancelled")

    lines = [l for l in ledger.order_lines(order["id"])
             if l["status"] in ("PROPOSED", "ALLOCATED")]
    order["status"] = "CANCELLED"
    if reason is not None:
        order["_cancel_reason"] = reason
    touch(order)
    if lines:
        ledger.revoke_lines(lines, "ORDER_CANCELLED")
    return object_response(order)


@bp.post("/channel-orders/<order_id>/ship")
def ship_order(order_id):
    authenticate(("ChannelManager",))
    order = get_order(order_id)
    payload = body()
    shipped_raw = None
    if present(payload, "shipped_at"):
        shipped_raw, _dt = instant_field(payload, "shipped_at")

    if order["status"] not in ("ALLOCATED", "PARTIAL"):
        fail("ERR_INVALID_STATE", "only an ALLOCATED or PARTIAL order may ship")
    if not Decimal(order["allocated_sqft"]) > 0:
        fail("ERR_INVALID_STATE", "the order holds no allocated coverage")

    booked = [l for l in ledger.order_lines(order["id"]) if l["status"] == "ALLOCATED"]
    lot_ids = []
    for line in booked:
        if line["inventory_lot_id"] not in lot_ids:
            lot_ids.append(line["inventory_lot_id"])
    for lot_id in lot_ids:
        lot = store.lots.get(lot_id)
        if lot is not None and lot["status"] == "QUARANTINED":
            fail("ERR_LOT_QUARANTINED", "lot %s is quarantined" % lot_id)

    order["status"] = "SHIPPED"
    if shipped_raw is not None:
        order["_shipped_at"] = shipped_raw
    touch(order)

    for lot_id in lot_ids:
        lot = store.lots.get(lot_id)
        if lot is None or lot["status"] != "ALLOCATED":
            continue
        exclusive = True
        for line in ledger.lot_lines(lot_id):
            if line["status"] == "ALLOCATED" and line["channel_order_id"] != order["id"]:
                exclusive = False
                break
        if exclusive:
            lot["status"] = "CONSUMED"
            lot["available_sqft"] = D0_2
            touch(lot)
    return object_response(order)


# ---------------------------------------------------------------------------
# AllocationLine
# ---------------------------------------------------------------------------

@bp.post("/allocation-lines")
def cut_manual_line():
    authenticate(("ChannelManager",))
    payload = body()
    amount = dec_field(payload, "allocated_sqft", gt=0)
    expected_version = int_field(payload, "expected_allocation_cycle_version")

    if not present(payload, "allocation_cycle_id"):
        fail("ERR_INVALID_REQUEST", "allocation_cycle_id is required")
    cycle = get_cycle(payload["allocation_cycle_id"])
    if not present(payload, "channel_order_id"):
        fail("ERR_INVALID_REQUEST", "channel_order_id is required")
    order = get_order(payload["channel_order_id"])
    if not present(payload, "inventory_lot_id"):
        fail("ERR_INVALID_REQUEST", "inventory_lot_id is required")
    lot = get_lot(payload["inventory_lot_id"])

    if expected_version != cycle["version"]:
        fail("ERR_STALE_ALLOCATION_CYCLE_VERSION",
             "expected_allocation_cycle_version does not match the cycle")

    if cycle["status"] not in ("OPEN", "PROPOSED"):
        fail("ERR_INVALID_STATE", "only an OPEN or PROPOSED cycle may host a manual line")
    if order["status"] not in OPEN_ORDER_STATUSES:
        fail("ERR_INVALID_STATE", "the order is not open for allocation")
    if order["product_line_id"] != cycle["product_line_id"]:
        fail("ERR_INVALID_STATE", "the order's SKU is not the cycle's SKU")
    if lot["product_line_id"] != cycle["product_line_id"] or lot["plant_id"] != cycle["plant_id"]:
        fail("ERR_INVALID_STATE", "the lot does not belong to the cycle's plant and SKU")
    if lot["status"] == "QUARANTINED":
        fail("ERR_LOT_QUARANTINED", "the lot is quarantined")
    if lot["status"] not in ("AVAILABLE", "ALLOCATED"):
        fail("ERR_INVALID_STATE", "the lot is no longer live")

    product_line = store.product_lines[cycle["product_line_id"]]
    bags = calc.exact_bag_multiple(amount, product_line["bag_sqft"])
    if bags is None:
        fail("ERR_BAG_MULTIPLE_MISMATCH",
             "allocated_sqft must be an exact positive multiple of bag_sqft")

    if Decimal(amount) > Decimal(lot["available_sqft"]) or \
            Decimal(order["allocated_sqft"]) + Decimal(amount) > Decimal(order["requested_sqft"]):
        fail("ERR_ALLOCATION_EXCEEDS_LOT_AVAILABLE",
             "the draw exceeds the lot's availability or the order's outstanding need")

    row = new_row()
    row.update({
        "allocation_cycle_id": cycle["id"],
        "channel_order_id": order["id"],
        "inventory_lot_id": lot["id"],
        "allocated_sqft": q2(amount),
        "bags": bags,
        "status": "ALLOCATED",
        "revoke_reason": None,
    })
    store.lines[row["id"]] = row

    ledger.recompute_lot(lot)
    ledger.recompute_order(order)
    ledger.recompute_cycle(cycle, bump=False)
    touch(cycle)
    return created_response(row)


@bp.get("/allocation-lines/<line_id>")
def read_line(line_id):
    authenticate(READ_ROLES)
    return object_response(get_line(line_id))


@bp.get("/allocation-lines")
def list_lines():
    authenticate(READ_ROLES)
    rows = apply_filters(store.lines.values(), {
        "allocation_cycle_id": ("allocation_cycle_id", "str"),
        "channel_order_id": ("channel_order_id", "str"),
        "inventory_lot_id": ("inventory_lot_id", "str"),
        "status": ("status", "str"),
    })
    return list_response(rows)


@bp.post("/allocation-lines/<line_id>/revoke")
def revoke_line(line_id):
    authenticate(("ChannelManager",))
    line = get_line(line_id)
    payload = body()
    note = str_field(payload, "revoke_note", required=False, default=None)
    if line["status"] not in ("PROPOSED", "ALLOCATED"):
        fail("ERR_INVALID_STATE", "only a PROPOSED or ALLOCATED line may be revoked")
    ledger.revoke_lines([line], "MANUAL_REVOKE", note=note)
    return object_response(line)
