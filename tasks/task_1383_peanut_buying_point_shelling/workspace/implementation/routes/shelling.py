"""ShellerContract, DeliveryCall, AllocationLine, HullLot (PRD 3.8, 3.9)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
from authz import (ADMIN, SHELLER, CLERK, authenticate, require_roles,
                   check_sheller_ownership)
from db import store
from errors import err, invalid_request, invalid_state, stale_version
from respond import success
from serialize import (ser_contract, ser_delivery_call, ser_allocation_line,
                       ser_hull_lot)
from store_ops import (get_or_404, json_body, list_response,
                       new_common_fields, new_junction_fields, req_bool,
                       req_datetime, req_int, req_str, req_tons, touch)

bp = Blueprint("shelling", __name__)


# ---------------------------------------------------------------------------
# ShellerContract
# ---------------------------------------------------------------------------

@bp.post("/buying-points/sheller-contracts")
def create_contract():
    authenticate()
    data = json_body()
    bp_id = req_str(data, "buying_point_id")
    sheller_ref = req_str(data, "sheller_ref")
    total_units = req_tons(data, "total_units_tons")
    price = req_int(data, "price_per_ton_cents", minimum=0)
    accepts_seg = req_bool(data, "accepts_segregated")
    window_start = req_datetime(data, "window_start")
    window_end = req_datetime(data, "window_end")
    if window_end < window_start:
        raise invalid_request("window_end must not precede window_start")
    require_roles([ADMIN])
    get_or_404(store.buying_points, bp_id)
    c = new_common_fields()
    c.update({
        "buying_point_id": bp_id,
        "sheller_ref": sheller_ref,
        "total_units_tons": calc.r3(total_units),
        "price_per_ton_cents": price,
        "accepts_segregated": accepts_seg,
        "window_start": window_start,
        "window_end": window_end,
        "default_count": 0,
        "status": "DRAFT",
    })
    store.sheller_contracts[c["id"]] = c
    return success(ser_contract(c), status=201)


@bp.get("/buying-points/sheller-contracts/<c_id>")
def get_contract(c_id):
    uid, role = require_roles([ADMIN, SHELLER, CLERK])
    c = get_or_404(store.sheller_contracts, c_id)
    check_sheller_ownership(uid, role, c)
    return success(ser_contract(c))


@bp.get("/buying-points/sheller-contracts")
def list_contracts():
    uid, role = require_roles([ADMIN, SHELLER, CLERK])
    items = list(store.sheller_contracts.values())
    if role == SHELLER:
        items = [c for c in items if c["sheller_ref"] == uid]
    for param, field in (("buying_point_id", "buying_point_id"),
                         ("sheller_ref", "sheller_ref"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return list_response(items, ser_contract)


@bp.post("/buying-points/sheller-contracts/<c_id>/activate")
def activate_contract(c_id):
    require_roles([ADMIN])
    c = get_or_404(store.sheller_contracts, c_id)
    if c["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT contract may be activated")
    c["status"] = "ACTIVE"
    touch(c)
    return success(ser_contract(c))


@bp.post("/buying-points/sheller-contracts/<c_id>/cancel")
def cancel_contract(c_id):
    require_roles([ADMIN])
    c = get_or_404(store.sheller_contracts, c_id)
    if c["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state("Only a DRAFT or ACTIVE contract may be cancelled")
    for call in store.delivery_calls.values():
        if call["contract_id"] == c["id"] and call["status"] in ("ISSUED", "ALLOCATED"):
            raise err("ERR_CONTRACT_HAS_OPEN_CALLS", 409,
                      "Open delivery calls block contract cancellation")
    c["status"] = "CANCELLED"
    touch(c)
    return success(ser_contract(c))


# ---------------------------------------------------------------------------
# DeliveryCall
# ---------------------------------------------------------------------------

@bp.post("/buying-points/delivery-calls")
def create_delivery_call():
    uid, role = authenticate()
    data = json_body()
    contract_id = req_str(data, "contract_id")
    requested = req_tons(data, "requested_tons")
    dock_start = req_datetime(data, "dock_window_start")
    dock_end = req_datetime(data, "dock_window_end")
    if dock_end < dock_start:
        raise invalid_request("dock_window_end must not precede dock_window_start")
    require_roles([SHELLER])
    contract = get_or_404(store.sheller_contracts, contract_id)
    check_sheller_ownership(uid, role, contract)
    if contract["status"] != "ACTIVE":
        raise invalid_state("Delivery calls require an ACTIVE contract")
    # Dock-window crowding (priority 9): the closed window, expanded by the
    # 120-minute turnaround buffer on both sides, may not intersect any other
    # non-terminal call's buffered window on the same contract.
    buf_start = dock_start - calc.TURNAROUND_BUFFER
    buf_end = dock_end + calc.TURNAROUND_BUFFER
    for o in store.delivery_calls.values():
        if o["contract_id"] != contract_id or o["status"] in ("RECONCILED", "CANCELLED", "DEFAULTED"):
            continue
        o_start = o["dock_window_start"] - calc.TURNAROUND_BUFFER
        o_end = o["dock_window_end"] + calc.TURNAROUND_BUFFER
        if buf_start <= o_end and o_start <= buf_end:
            raise err("ERR_DOCK_WINDOW_OVERLAP", 409,
                      "The buffered dock window intersects another call's window")
    # Temporal (priority 10): dock window fully inside the contract window.
    if dock_start < contract["window_start"] or dock_end > contract["window_end"]:
        raise err("ERR_DOCK_WINDOW_OUTSIDE_CONTRACT", 409,
                  "The dock window must fit inside the contract window")
    # Fiscal (priority 11): remaining tonnage.
    if requested > calc.contract_remaining_tons(contract_id):
        raise err("ERR_CONTRACT_REMAINING_EXCEEDED", 409,
                  "requested_tons exceeds the contract's remaining tonnage")
    c = new_common_fields()
    c.update({
        "contract_id": contract_id,
        "requested_tons": calc.r3(requested),
        "dock_window_start": dock_start,
        "dock_window_end": dock_end,
        "status": "ISSUED",
    })
    store.delivery_calls[c["id"]] = c
    return success(ser_delivery_call(c), status=201)


@bp.get("/buying-points/delivery-calls/<c_id>")
def get_delivery_call(c_id):
    uid, role = require_roles([ADMIN, SHELLER, CLERK])
    c = get_or_404(store.delivery_calls, c_id)
    if role == SHELLER:
        contract = store.sheller_contracts.get(c["contract_id"])
        check_sheller_ownership(uid, role, contract)
    return success(ser_delivery_call(c))


@bp.get("/buying-points/delivery-calls")
def list_delivery_calls():
    uid, role = require_roles([ADMIN, SHELLER, CLERK])
    items = list(store.delivery_calls.values())
    if role == SHELLER:
        items = [c for c in items
                 if store.sheller_contracts.get(c["contract_id"]) is not None
                 and store.sheller_contracts[c["contract_id"]]["sheller_ref"] == uid]
    for param, field in (("contract_id", "contract_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return list_response(items, ser_delivery_call)


def _release_call_lines(call):
    doomed = [lid for lid, l in store.allocation_lines.items()
              if l["delivery_call_id"] == call["id"]]
    for lid in doomed:
        del store.allocation_lines[lid]


@bp.post("/buying-points/delivery-calls/<c_id>/allocate")
def allocate_delivery_call(c_id):
    authenticate()
    data = json_body()
    expected = req_int(data, "expected_delivery_call_version")
    require_roles([ADMIN])
    call = get_or_404(store.delivery_calls, c_id)
    if call["status"] not in ("ISSUED", "ALLOCATED"):
        raise invalid_state("Only an ISSUED or ALLOCATED call may be allocated")
    if expected != call["version"]:
        raise stale_version()
    contract = store.sheller_contracts[call["contract_id"]]
    # Atomicity: the selector validates total sufficiency BEFORE any line is
    # deleted or persisted (no partial set on rejection).
    eligible = calc.eligible_receipts(contract["buying_point_id"],
                                      contract["accepts_segregated"])
    total_available = sum((r["tons_remaining"] for r in eligible), Decimal(0))
    if total_available < call["requested_tons"]:
        raise err("ERR_INSUFFICIENT_ALLOCABLE_TONS", 409,
                  "Eligible open receipts cannot cover the requested tonnage")
    _release_call_lines(call)  # re-allocation supersedes prior lines
    need = call["requested_tons"]
    for receipt in eligible:
        if need <= 0:
            break
        line_tons = min(receipt["tons_remaining"], need)
        line = new_junction_fields()
        line.update({
            "delivery_call_id": call["id"],
            "storage_receipt_id": receipt["id"],
            "allocated_tons": calc.r3(line_tons),
            "shipped_tons": Decimal(0),
            "shelled_tons": Decimal(0),
        })
        store.allocation_lines[line["id"]] = line
        need -= line_tons
    call["status"] = "ALLOCATED"
    touch(call)
    return success(ser_delivery_call(call))


@bp.post("/buying-points/delivery-calls/<c_id>/deliver")
def deliver_delivery_call(c_id):
    require_roles([ADMIN])
    call = get_or_404(store.delivery_calls, c_id)
    if call["status"] != "ALLOCATED":
        raise invalid_state("Only an ALLOCATED call may be delivered")
    # Full truckout: every line ships its allocated tonnage.
    for line in calc.lines_of_call(call["id"]):
        line["shipped_tons"] = line["allocated_tons"]
        receipt = store.storage_receipts.get(line["storage_receipt_id"])
        if receipt is None:
            continue
        receipt["tons_remaining"] = calc.r3(receipt["tons_remaining"] - line["shipped_tons"])
        if receipt["tons_remaining"] == 0 and receipt["status"] == "OPEN":
            receipt["status"] = "CLOSED"
            load = store.loads.get(receipt["load_id"])
            if load is not None and load["status"] == "STORED":
                load["status"] = "DEPLETED"
                touch(load)
        touch(receipt)
    call["status"] = "DELIVERED"
    touch(call)
    contract = store.sheller_contracts.get(call["contract_id"])
    if contract is not None and contract["status"] == "ACTIVE":
        if calc.contract_fulfilled_tons(contract["id"]) >= contract["total_units_tons"]:
            contract["status"] = "FULFILLED"  # boundary: equality counts
            touch(contract)
    return success(ser_delivery_call(call))


@bp.post("/buying-points/delivery-calls/<c_id>/reconcile")
def reconcile_delivery_call(c_id):
    uid, role = authenticate()
    data = json_body()
    shelled = req_tons(data, "shelled_kernel_tons", allow_zero=True)
    hull = req_tons(data, "hull_tons", allow_zero=True)
    require_roles([SHELLER])
    call = get_or_404(store.delivery_calls, c_id)
    contract = store.sheller_contracts.get(call["contract_id"])
    check_sheller_ownership(uid, role, contract)
    if call["status"] != "DELIVERED":
        raise invalid_state("Only a DELIVERED call may be reconciled")
    delivered = calc.call_delivered_tons(call["id"])
    shrink = delivered - shelled - hull
    if shelled + hull > delivered or shrink > delivered * calc.SHRINK_ALLOWANCE_PCT:
        raise err("ERR_HULL_RECONCILE_MISMATCH", 409,
                  "Shelled plus hull exceeds delivered tonnage or shrink tolerance")
    # Attribute shelled kernel tonnage pro-rata by shipped_tons at 3-decimal
    # rounding; any remainder goes to the earliest-created line.
    lines = calc.lines_of_call(call["id"])
    if lines and delivered > 0:
        parts = [calc.r3(shelled * line["shipped_tons"] / delivered) for line in lines]
        remainder = shelled - sum(parts, Decimal(0))
        for line, part in zip(lines, parts):
            line["shelled_tons"] = part
        lines[0]["shelled_tons"] = calc.r3(lines[0]["shelled_tons"] + remainder)
    lot = new_common_fields()
    lot.update({
        "delivery_call_id": call["id"],
        "tons": calc.r3(hull),
        "sale_price_cents_per_ton": None,
        "revenue_cents": None,
        "sold_at": None,
        "disposition_ref": None,
        "status": "GENERATED",
    })
    store.hull_lots[lot["id"]] = lot
    call["status"] = "RECONCILED"
    touch(call)
    return success(ser_delivery_call(call))


@bp.post("/buying-points/delivery-calls/<c_id>/cancel")
def cancel_delivery_call(c_id):
    uid, role = require_roles([ADMIN, SHELLER])
    call = get_or_404(store.delivery_calls, c_id)
    if role == SHELLER:
        contract = store.sheller_contracts.get(call["contract_id"])
        check_sheller_ownership(uid, role, contract)
    if call["status"] not in ("ISSUED", "ALLOCATED"):
        raise invalid_state("Only an ISSUED or ALLOCATED call may be cancelled")
    if call["status"] == "ALLOCATED":
        _release_call_lines(call)
    call["status"] = "CANCELLED"
    touch(call)
    return success(ser_delivery_call(call))


# ---------------------------------------------------------------------------
# AllocationLine (read-only junction)
# ---------------------------------------------------------------------------

@bp.get("/buying-points/allocation-lines/<l_id>")
def get_allocation_line(l_id):
    require_roles([ADMIN, CLERK])
    line = get_or_404(store.allocation_lines, l_id)
    return success(ser_allocation_line(line))


@bp.get("/buying-points/allocation-lines")
def list_allocation_lines():
    require_roles([ADMIN, CLERK])
    items = list(store.allocation_lines.values())
    for param, field in (("delivery_call_id", "delivery_call_id"),
                         ("storage_receipt_id", "storage_receipt_id")):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[field] == v]
    return list_response(items, ser_allocation_line)


# ---------------------------------------------------------------------------
# HullLot
# ---------------------------------------------------------------------------

@bp.get("/buying-points/hull-lots/<h_id>")
def get_hull_lot(h_id):
    require_roles([ADMIN, CLERK])
    lot = get_or_404(store.hull_lots, h_id)
    return success(ser_hull_lot(lot))


@bp.get("/buying-points/hull-lots")
def list_hull_lots():
    require_roles([ADMIN, CLERK])
    items = list(store.hull_lots.values())
    for param, field in (("delivery_call_id", "delivery_call_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[field] == v]
    return list_response(items, ser_hull_lot)


@bp.post("/buying-points/hull-lots/<h_id>/list-for-sale")
def list_hull_lot_for_sale(h_id):
    authenticate()
    data = json_body()
    price = req_int(data, "sale_price_cents_per_ton", minimum=0)
    require_roles([ADMIN])
    lot = get_or_404(store.hull_lots, h_id)
    if lot["status"] != "GENERATED":
        raise invalid_state("Only a GENERATED hull lot may be listed for sale")
    lot["sale_price_cents_per_ton"] = price
    lot["status"] = "LISTED"
    touch(lot)
    return success(ser_hull_lot(lot))


@bp.post("/buying-points/hull-lots/<h_id>/sell")
def sell_hull_lot(h_id):
    require_roles([ADMIN])
    lot = get_or_404(store.hull_lots, h_id)
    if lot["status"] != "LISTED":
        raise invalid_state("Only a LISTED hull lot may be sold")
    lot["revenue_cents"] = calc.r0(lot["tons"] * lot["sale_price_cents_per_ton"])
    lot["sold_at"] = store.clock
    lot["status"] = "SOLD"
    touch(lot)
    return success(ser_hull_lot(lot))


@bp.post("/buying-points/hull-lots/<h_id>/dispose")
def dispose_hull_lot(h_id):
    authenticate()
    data = json_body()
    disposition_ref = req_str(data, "disposition_ref")
    require_roles([ADMIN])
    lot = get_or_404(store.hull_lots, h_id)
    if lot["status"] not in ("GENERATED", "LISTED"):
        raise invalid_state("Only a GENERATED or LISTED hull lot may be disposed")
    lot["disposition_ref"] = disposition_ref
    lot["status"] = "DISPOSED"
    touch(lot)
    return success(ser_hull_lot(lot))
