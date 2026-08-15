"""Shipments, temperature readings, and dock decisions (PRD section 3.7)."""

import uuid

from flask import Blueprint, request

from store import TABLES
from helpers import (
    auth, own_or_fail, success, err, get_body, req_str, req_num,
    req_positive_num, paginate, sorted_by_created, stamp_new, touch, path_get,
    require_ref, find, num_out, dec, q2, recompute_warehouse,
    recompute_all_warehouses, recompute_customer_exposure, shipment_customer_id,
    lot_public, make_lot,
)

bp = Blueprint("logistics", __name__)

WAREHOUSE = ["WarehouseOperator"]
CUSTREP = ["CustomerRep"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]


def shipment_public(s):
    return {
        "id": s["id"],
        "allocation_id": s["allocation_id"],
        "carrier_name": s["carrier_name"],
        "trailer_temp_setpoint_f": num_out(s["trailer_temp_setpoint_f"]),
        "shipped_lbs": num_out(s["shipped_lbs"]),
        "lot_ids": [lid for (lid, _w) in s["_drawn"]],
        "min_temp_f_reading": num_out(s["min_temp_f_reading"]),
        "max_temp_f_reading": num_out(s["max_temp_f_reading"]),
        "temp_compliance": s["temp_compliance"],
        "rejection_reason": s["rejection_reason"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def reading_public(r):
    return {
        "id": r["id"],
        "shipment_id": r["shipment_id"],
        "reading_f": num_out(r["reading_f"]),
        "recorded_at": r["recorded_at"],
        "created_at": r["created_at"],
    }


def shipment_product(shipment):
    alloc = find("allocations", shipment["allocation_id"])
    if alloc is None:
        return None
    line = find("price_sheet_lines", alloc["price_sheet_line_id"])
    if line is None:
        return None
    return find("products", line["product_id"])


# ---------------------------------------------------------------------------
# Shipment creation (load-out)
# ---------------------------------------------------------------------------

@bp.route("/api/shipments", methods=["POST"])
def create_shipment():
    auth(WAREHOUSE)
    body = get_body()
    allocation_id = req_str(body, "allocation_id")
    carrier = req_str(body, "carrier_name")
    setpoint = req_num(body, "trailer_temp_setpoint_f")
    shipped = req_positive_num(body, "shipped_lbs")
    lot_ids_raw = body.get("lot_ids")
    lot_ids = None
    if lot_ids_raw is not None:
        if not isinstance(lot_ids_raw, list) or any(not isinstance(x, str) for x in lot_ids_raw):
            err("ERR_INVALID_REQUEST", 400, "lot_ids must be an array of strings")
        lot_ids = lot_ids_raw
    shipped = q2(shipped)
    # Body FK existence (priority 6).
    alloc = require_ref("allocations", allocation_id, "allocation_id")
    if lot_ids:
        for lid in lot_ids:
            require_ref("inventory_lots", lid, "lot_ids")
    # Target state (priority 7): allocation must be CONFIRMED.
    if alloc["status"] != "CONFIRMED":
        err("ERR_INVALID_STATE", 409,
            "Shipments may only be created against a CONFIRMED allocation")
    line = find("price_sheet_lines", alloc["price_sheet_line_id"])
    product_id = line["product_id"] if line else None
    # Safety (priority 9): explicit lots must be AVAILABLE and not EXPIRED.
    if lot_ids:
        for lid in lot_ids:
            lot = TABLES["inventory_lots"][lid]
            if lot["status"] == "EXPIRED":
                err("ERR_LOT_EXPIRED", 409, f"Lot {lid} is EXPIRED")
            if lot["status"] != "AVAILABLE":
                err("ERR_LOT_NOT_AVAILABLE", 409, f"Lot {lid} is not AVAILABLE")
    # Structural (priority 10): weight may not exceed the remaining balance.
    already = dec(0)
    for s in TABLES["shipments"].values():
        if s["allocation_id"] == alloc["id"]:
            already += dec(s["shipped_lbs"])
    if shipped > dec(alloc["allocated_lbs"]) - already:
        err("ERR_SHIPMENT_EXCEEDS_ALLOCATION", 422,
            "shipped_lbs exceeds the allocation's remaining unshipped weight")
    # Kind compatibility (priority 13): explicit lot products must match.
    if lot_ids:
        for lid in lot_ids:
            lot = TABLES["inventory_lots"][lid]
            if lot["product_id"] != product_id:
                err("ERR_LOT_PRODUCT_MISMATCH", 422,
                    f"Lot {lid} product differs from the allocation product")
    # Draw the lots: explicit order, or FIFO by (production_date, created_at).
    drawn = []
    if lot_ids:
        need = shipped
        for lid in lot_ids:
            if need <= 0:
                break
            lot = TABLES["inventory_lots"][lid]
            take = min(need, dec(lot["current_weight_lbs"]))
            if take > 0:
                drawn.append((lid, take))
                need -= take
        if need > 0:
            err("ERR_INSUFFICIENT_SUPPLY", 409,
                "The named lots cannot cover shipped_lbs")
    else:
        # FIFO pool sufficiency (priority 16) — check before decrementing.
        pool = [l for l in TABLES["inventory_lots"].values()
                if l["status"] == "AVAILABLE" and l["product_id"] == product_id]
        pool.sort(key=lambda l: (l["production_date"], l["_seq"]))
        total_available = sum((dec(l["current_weight_lbs"]) for l in pool), dec(0))
        if total_available < shipped:
            err("ERR_INSUFFICIENT_SUPPLY", 409,
                "AVAILABLE lots of the product cannot cover shipped_lbs")
        need = shipped
        for lot in pool:
            if need <= 0:
                break
            take = min(need, dec(lot["current_weight_lbs"]))
            if take > 0:
                drawn.append((lot["id"], take))
                need -= take
    # Commit the draw.
    for lid, take in drawn:
        lot = TABLES["inventory_lots"][lid]
        lot["current_weight_lbs"] = q2(dec(lot["current_weight_lbs"]) - take)
        if lot["current_weight_lbs"] == 0:
            lot["status"] = "DEPLETED"
        touch(lot)
    rec = {
        "allocation_id": alloc["id"],
        "carrier_name": carrier,
        "trailer_temp_setpoint_f": setpoint,
        "shipped_lbs": shipped,
        "min_temp_f_reading": None,
        "max_temp_f_reading": None,
        "temp_compliance": "UNKNOWN",
        "rejection_reason": None,
        "status": "STAGING",
        "_drawn": drawn,
    }
    stamp_new(rec)
    TABLES["shipments"][rec["id"]] = rec
    recompute_all_warehouses()
    return success(shipment_public(rec), code=201)


@bp.route("/api/shipments", methods=["GET"])
def list_shipments():
    auth(ALL)
    items = sorted_by_created(TABLES["shipments"].values())
    allocation_id = request.args.get("allocation_id")
    status = request.args.get("status")
    temp = request.args.get("temp_compliance")
    if allocation_id is not None:
        items = [s for s in items if s["allocation_id"] == allocation_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if temp is not None:
        items = [s for s in items if s["temp_compliance"] == temp]
    page, meta = paginate(items)
    return success([shipment_public(s) for s in page], response_type="array",
                   pagination=meta)


@bp.route("/api/shipments/<shipmentId>", methods=["GET"])
def get_shipment(shipmentId):
    auth(ALL)
    s = path_get("shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
    return success(shipment_public(s))


# ---------------------------------------------------------------------------
# Temperature readings (parallel temp_compliance axis; sticky BREACHED)
# ---------------------------------------------------------------------------

@bp.route("/api/shipments/<shipmentId>/temperature-readings", methods=["POST"])
def add_reading(shipmentId):
    auth(WAREHOUSE)
    body = get_body()
    reading = req_num(body, "reading_f")
    recorded_at = req_str(body, "recorded_at")
    from helpers import parse_iso_datetime
    parse_iso_datetime(recorded_at, "recorded_at")
    shipment = path_get("shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
    rec = {
        "shipment_id": shipment["id"],
        "reading_f": reading,
        "recorded_at": recorded_at,
    }
    stamp_new(rec, common=False)
    TABLES["temperature_readings"][rec["id"]] = rec
    # Fold into min/max and re-evaluate the compliance axis.
    cur_min = shipment["min_temp_f_reading"]
    cur_max = shipment["max_temp_f_reading"]
    shipment["min_temp_f_reading"] = reading if cur_min is None else min(dec(cur_min), reading)
    shipment["max_temp_f_reading"] = reading if cur_max is None else max(dec(cur_max), reading)
    product = shipment_product(shipment)
    if product is not None:
        ceiling = dec(product["required_temp_max_f"])
        if reading > ceiling:
            shipment["temp_compliance"] = "BREACHED"  # sticky
        elif shipment["temp_compliance"] == "UNKNOWN":
            shipment["temp_compliance"] = "COMPLIANT"
    touch(shipment)
    return success(reading_public(rec), code=201)


@bp.route("/api/shipments/<shipmentId>/temperature-readings", methods=["GET"])
def list_readings(shipmentId):
    auth(ALL)
    shipment = path_get("shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
    items = [r for r in sorted_by_created(TABLES["temperature_readings"].values())
             if r["shipment_id"] == shipment["id"]]
    page, meta = paginate(items)
    return success([reading_public(r) for r in page], response_type="array",
                   pagination=meta)


# ---------------------------------------------------------------------------
# Depart / deliver / reject
# ---------------------------------------------------------------------------

@bp.route("/api/shipments/<shipmentId>/depart", methods=["POST"])
def depart_shipment(shipmentId):
    auth(WAREHOUSE)
    shipment = path_get("shipments", shipmentId, "ERR_SHIPMENT_NOT_FOUND")
    if shipment["status"] != "STAGING":
        err("ERR_SHIPMENT_NOT_STAGING", 409, "Only a STAGING shipment may depart")
    has_reading = any(r["shipment_id"] == shipment["id"]
                      for r in TABLES["temperature_readings"].values())
    if not has_reading:
        err("ERR_NO_TEMPERATURE_READING", 409,
            "Departure requires at least one temperature reading")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    # Desk policy: departure triggers an exposure recompute that cannot move
    # the figure (allocation value stays in exposure while CONFIRMED).
    customer = find("customers", shipment_customer_id(shipment))
    if customer is not None:
        recompute_customer_exposure(customer)
    return success(shipment_public(shipment))


@bp.route("/api/shipments/<shipmentId>/deliver", methods=["POST"])
def deliver_shipment(shipmentId):
    uid, _ = auth(CUSTREP)
    shipment = TABLES["shipments"].get(shipmentId)
    if shipment is not None:
        own_or_fail(shipment_customer_id(shipment), uid)
    if shipment is None:
        err("ERR_SHIPMENT_NOT_FOUND", 404, f"Shipment {shipmentId} not found")
    if shipment["status"] != "IN_TRANSIT":
        err("ERR_SHIPMENT_NOT_IN_TRANSIT", 409,
            "Only an IN_TRANSIT shipment may be delivered")
    shipment["status"] = "DELIVERED"
    touch(shipment)
    alloc = find("allocations", shipment["allocation_id"])
    # Earmarked delivery feeds the contract and may settle it.
    if alloc is not None and alloc.get("forward_contract_id"):
        contract = find("forward_contracts", alloc["forward_contract_id"])
        if contract is not None:
            contract["delivered_lbs"] = q2(dec(contract["delivered_lbs"])
                                           + dec(shipment["shipped_lbs"]))
            if contract["status"] == "OPEN" and \
                    dec(contract["delivered_lbs"]) >= dec(contract["committed_lbs"]):
                contract["status"] = "SETTLED"
            touch(contract)
    # The allocation ships when cumulative delivered weight covers the grant.
    if alloc is not None and alloc["status"] == "CONFIRMED":
        delivered_total = dec(0)
        for s in TABLES["shipments"].values():
            if s["allocation_id"] == alloc["id"] and s["status"] == "DELIVERED":
                delivered_total += dec(s["shipped_lbs"])
        if delivered_total >= dec(alloc["allocated_lbs"]):
            alloc["status"] = "SHIPPED"
            touch(alloc)
    customer = find("customers", shipment_customer_id(shipment))
    if customer is not None:
        recompute_customer_exposure(customer)
    return success(shipment_public(shipment))


@bp.route("/api/shipments/<shipmentId>/reject", methods=["POST"])
def reject_shipment(shipmentId):
    uid, _ = auth(CUSTREP)
    shipment = TABLES["shipments"].get(shipmentId)
    if shipment is not None:
        own_or_fail(shipment_customer_id(shipment), uid)
    body = get_body()
    reason = req_str(body, "rejection_reason")
    if shipment is None:
        err("ERR_SHIPMENT_NOT_FOUND", 404, f"Shipment {shipmentId} not found")
    if shipment["status"] != "IN_TRANSIT":
        err("ERR_SHIPMENT_NOT_IN_TRANSIT", 409,
            "Only an IN_TRANSIT shipment may be rejected")
    shipment["status"] = "REJECTED_AT_RECEIVING"
    shipment["rejection_reason"] = reason
    touch(shipment)
    # Cascade link 1: create the returns lot, QUARANTINED at the source
    # warehouse, with the oldest drawn lot's production date.
    alloc = find("allocations", shipment["allocation_id"])
    line = find("price_sheet_lines", alloc["price_sheet_line_id"]) if alloc else None
    product_id = line["product_id"] if line else None
    drawn_lots = [TABLES["inventory_lots"].get(lid) for (lid, _w) in shipment["_drawn"]]
    drawn_lots = [l for l in drawn_lots if l is not None]
    oldest = None
    if drawn_lots:
        oldest = min(drawn_lots, key=lambda l: (l["production_date"], l["_seq"]))
    source_warehouse = oldest["warehouse_id"] if oldest else None
    production_date = oldest["production_date"] if oldest else None
    if source_warehouse is None:
        # No recorded draw (defensive): fall back to any warehouse.
        wh = next(iter(TABLES["warehouses"].values()), None)
        source_warehouse = wh["id"] if wh else None
    make_lot(
        lot_code=f"RET-{uuid.uuid4().hex[:12].upper()}",
        product_id=product_id,
        warehouse_id=source_warehouse,
        weight_lbs=shipment["shipped_lbs"],
        production_date=production_date or "1970-01-01",
        status="QUARANTINED",
        quarantine_reason="RETURNED_REJECTED",
    )
    # Cascade link 2: occupancy recomputed for the returned weight.
    if source_warehouse is not None:
        recompute_warehouse(source_warehouse)
    return success(shipment_public(shipment))
