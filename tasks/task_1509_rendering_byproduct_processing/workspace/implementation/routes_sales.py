"""CustomerContract, SalesOrder, and PriceIndexEntry endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import db
from common import (caller, require_role, body_json, v_str, v_int, v_num,
                    v_enum, v_date, v_list, ok, view, stamp_new, touch,
                    paginate, sorted_items, get_or_404, fail, rhu)
from logic import (posture_gate, current_settlement, lot_view, lot_meets_spec,
                   available_lbs, release_order_allocations, FAT_TYPES,
                   GRADE_MULT, FREIGHT_FLAT_CENTS)

bp = Blueprint("sales", __name__)

PRODUCT_TYPES = {"TALLOW", "YELLOW_GREASE", "PROTEIN_MEAL", "FEATHER_MEAL"}
INDEX_PRODUCTS = {"TALLOW", "MEAL"}
INDEX_SOURCES = {"USDA_AMS", "JACOBSEN", "INTERNAL"}
EXPECTED_GRADES = {"PREMIUM", "STANDARD", "FEED_GRADE"}


# ---------------- customer contracts ----------------

@bp.post("/rendering/customer-contracts")
def create_contract():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    customer_name = v_str(b, "customer_name")
    product_type = v_enum(b, "product_type", PRODUCT_TYPES)
    spec_moisture = v_num(b, "spec_max_moisture_pct")
    spec_ffa = v_num(b, "spec_max_ffa_pct")
    spec_protein = v_num(b, "spec_min_protein_pct")
    pricing_mode = v_enum(b, "pricing_mode", {"FIXED", "INDEX_LINKED"})
    base_price = v_int(b, "base_price_cents_per_lb", required=(pricing_mode == "FIXED"))
    index_product = v_enum(b, "index_product", INDEX_PRODUCTS,
                           required=(pricing_mode == "INDEX_LINKED"))
    basis_adj = v_int(b, "index_basis_adjustment_cents",
                      required=(pricing_mode == "INDEX_LINKED"))
    volume_commitment = v_int(b, "volume_commitment_lbs", minv=0)
    tier_discounts = v_list(b, "tier_discounts")
    for t in tier_discounts:
        if not isinstance(t, dict):
            fail("ERR_INVALID_REQUEST", 400, "tier_discounts entries must be objects")
        tw = t.get("threshold_lbs")
        if isinstance(tw, bool) or not isinstance(tw, int) or tw < 0:
            fail("ERR_INVALID_REQUEST", 400, "tier_discounts.threshold_lbs must be an integer >= 0")
        dp = t.get("discount_pct")
        if isinstance(dp, bool) or not isinstance(dp, (int, float)):
            fail("ERR_INVALID_REQUEST", 400, "tier_discounts.discount_pct must be a number")
    margin_floor = v_num(b, "margin_floor_pct")
    eff_from = v_date(b, "effective_from")
    eff_to = v_date(b, "effective_to")
    if eff_to < eff_from:
        fail("ERR_INVALID_REQUEST", 400, "effective_to must be >= effective_from")
    require_role(role, "SalesManager")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "admin")
    c = {
        "plant_id": plant_id,
        "customer_name": customer_name,
        "product_type": product_type,
        "spec_max_moisture_pct": spec_moisture,
        "spec_max_ffa_pct": spec_ffa,
        "spec_min_protein_pct": spec_protein,
        "pricing_mode": pricing_mode,
        "base_price_cents_per_lb": base_price,
        "index_product": index_product,
        "index_basis_adjustment_cents": basis_adj,
        "volume_commitment_lbs": volume_commitment,
        "tier_discounts": [{"threshold_lbs": t["threshold_lbs"], "discount_pct": t["discount_pct"]}
                           for t in tier_discounts],
        "margin_floor_pct": margin_floor,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "delivered_volume_lbs": 0,
        "created_by": uid,
        "status": "DRAFT",
    }
    stamp_new(c)
    db.STORES["contracts"][c["id"]] = c
    return ok(view(c), 201)


@bp.get("/rendering/customer-contracts")
def list_contracts():
    caller()
    items = sorted_items("contracts", {
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
        "product_type": request.args.get("product_type"),
    })
    return paginate(items)


@bp.get("/rendering/customer-contracts/<cid>")
def get_contract(cid):
    caller()
    return ok(view(get_or_404("contracts", cid, "ERR_CONTRACT_NOT_FOUND")), 200)


def _contract_ctx(cid):
    c = get_or_404("contracts", cid, "ERR_CONTRACT_NOT_FOUND")
    plant = get_or_404("plants", c["plant_id"], "ERR_PLANT_NOT_FOUND")
    return c, plant


@bp.post("/rendering/customer-contracts/<cid>/submit")
def submit_contract(cid):
    uid, role = caller()
    require_role(role, "SalesManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] != "DRAFT":
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract must be DRAFT to submit")
    c["status"] = "SUBMITTED"
    touch(c)
    return ok(view(c), 200)


@bp.post("/rendering/customer-contracts/<cid>/approve")
def approve_contract(cid):
    uid, role = caller()
    require_role(role, "PlantManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] != "SUBMITTED":
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract must be SUBMITTED to approve")
    if c["created_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Approver must differ from creator")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(view(c), 200)


@bp.post("/rendering/customer-contracts/<cid>/return-to-draft")
def return_contract(cid):
    uid, role = caller()
    require_role(role, "PlantManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] != "SUBMITTED":
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract must be SUBMITTED to return to draft")
    c["status"] = "DRAFT"
    touch(c)
    return ok(view(c), 200)


@bp.post("/rendering/customer-contracts/<cid>/suspend")
def suspend_contract(cid):
    uid, role = caller()
    require_role(role, "SalesManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] != "ACTIVE":
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract must be ACTIVE to suspend")
    c["status"] = "SUSPENDED"
    touch(c)
    return ok(view(c), 200)


@bp.post("/rendering/customer-contracts/<cid>/reinstate")
def reinstate_contract(cid):
    uid, role = caller()
    require_role(role, "SalesManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] != "SUSPENDED":
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract must be SUSPENDED to reinstate")
    c["status"] = "ACTIVE"
    touch(c)
    return ok(view(c), 200)


@bp.post("/rendering/customer-contracts/<cid>/terminate")
def terminate_contract(cid):
    uid, role = caller()
    require_role(role, "SalesManager")
    c, plant = _contract_ctx(cid)
    posture_gate(plant, "admin")
    if c["status"] not in ("ACTIVE", "SUSPENDED", "DRAFT", "SUBMITTED"):
        fail("ERR_CONTRACT_INVALID_STATE", 409, "Contract cannot be terminated from its state")
    c["status"] = "TERMINATED"
    touch(c)
    for order in db.STORES["orders"].values():
        if order["contract_id"] == c["id"] and order["status"] in ("DRAFT", "PRICED"):
            order["status"] = "CANCELLED"
            touch(order)
    return ok(view(c), 200)


# ---------------- sales orders ----------------

@bp.post("/rendering/sales-orders")
def create_order():
    uid, role = caller()
    b = body_json()
    contract_id = v_str(b, "contract_id")
    plant_id = v_str(b, "plant_id")
    quantity = v_int(b, "quantity_lbs", minv=1)
    ship_date = v_date(b, "requested_ship_date")
    expected_version = v_int(b, "expected_contract_version")
    require_role(role, "SalesManager")
    contract = get_or_404("contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    if contract["plant_id"] != plant_id:
        fail("ERR_INVALID_REQUEST", 400, "plant_id must equal the contract's plant")
    posture_gate(plant, "op")
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract must be ACTIVE")
    if contract["version"] != expected_version:
        fail("ERR_STALE_VERSION", 412, "expected_contract_version does not match current version")
    if not (contract["effective_from"] <= ship_date <= contract["effective_to"]):
        fail("ERR_CONTRACT_NOT_IN_EFFECT", 422, "requested_ship_date outside the contract window")
    order = {
        "contract_id": contract_id,
        "plant_id": plant_id,
        "quantity_lbs": quantity,
        "requested_ship_date": ship_date,
        "unit_price_cents": None,
        "applied_index_price_cents": None,
        "applied_discount_pct": None,
        "gross_amount_cents": None,
        "discount_amount_cents": None,
        "freight_surcharge_cents": None,
        "net_amount_cents": None,
        "margin_pct": None,
        "allocations": [],
        "shipped_vehicle_id": None,
        "status": "DRAFT",
    }
    stamp_new(order)
    db.STORES["orders"][order["id"]] = order
    touch(contract)
    return ok(view(order), 201)


@bp.get("/rendering/sales-orders")
def list_orders():
    caller()
    items = sorted_items("orders", {
        "contract_id": request.args.get("contract_id"),
        "plant_id": request.args.get("plant_id"),
        "status": request.args.get("status"),
    })
    return paginate(items)


@bp.get("/rendering/sales-orders/<oid>")
def get_order(oid):
    caller()
    return ok(view(get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")), 200)


def _order_ctx(oid):
    order = get_or_404("orders", oid, "ERR_ORDER_NOT_FOUND")
    plant = get_or_404("plants", order["plant_id"], "ERR_PLANT_NOT_FOUND")
    contract = get_or_404("contracts", order["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    return order, plant, contract


@bp.post("/rendering/sales-orders/<oid>/price")
def price_order(oid):
    uid, role = caller()
    b = body_json()
    expected_grade = v_enum(b, "expected_grade", EXPECTED_GRADES)
    require_role(role, "SalesManager")
    order, plant, contract = _order_ctx(oid)
    posture_gate(plant, "op")
    if order["status"] != "DRAFT":
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be DRAFT to price")
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract must be ACTIVE")
    if not (contract["effective_from"] <= order["requested_ship_date"] <= contract["effective_to"]):
        fail("ERR_CONTRACT_NOT_IN_EFFECT", 422, "requested_ship_date outside the contract window")
    if contract["pricing_mode"] == "FIXED":
        base = contract["base_price_cents_per_lb"]
        applied_index = None
    else:
        candidates = [e for e in db.STORES["index_entries"].values()
                      if e["plant_id"] == plant["id"]
                      and e["index_product"] == contract["index_product"]
                      and e["effective_date"] <= order["requested_ship_date"]]
        if not candidates:
            fail("ERR_NO_INDEX_FOR_DATE", 422,
                 "No price index entry on or before the requested ship date")
        candidates.sort(key=lambda e: (e["effective_date"], e["_seq"]))
        idx = candidates[-1]
        base = idx["price_cents_per_lb"] + contract["index_basis_adjustment_cents"]
        applied_index = idx["price_cents_per_lb"]
    unit_price = int(rhu(Decimal(base) * GRADE_MULT[expected_grade]))
    gross = order["quantity_lbs"] * unit_price
    projected = contract["delivered_volume_lbs"] + order["quantity_lbs"]
    discount_pct = 0
    for t in sorted(contract["tier_discounts"], key=lambda x: x["threshold_lbs"]):
        if projected >= t["threshold_lbs"]:
            discount_pct = t["discount_pct"]
    discount_amount = int(rhu(Decimal(gross) * Decimal(str(discount_pct))))
    freight = FREIGHT_FLAT_CENTS
    net = gross - discount_amount + freight
    if unit_price > 0:
        margin = float(rhu(Decimal(unit_price - plant["standard_cost_cents_per_lb"])
                           / Decimal(unit_price) * 100, 2))
    else:
        margin = 0.0
    order["unit_price_cents"] = unit_price
    order["applied_index_price_cents"] = applied_index
    order["applied_discount_pct"] = discount_pct
    order["gross_amount_cents"] = gross
    order["discount_amount_cents"] = discount_amount
    order["freight_surcharge_cents"] = freight
    order["net_amount_cents"] = net
    order["margin_pct"] = margin
    order["status"] = "PRICED"
    touch(order)
    return ok(view(order), 200)


@bp.post("/rendering/sales-orders/<oid>/confirm")
def confirm_order(oid):
    uid, role = caller()
    b = body_json()
    allocations = v_list(b, "allocations")
    for a in allocations:
        if not isinstance(a, dict):
            fail("ERR_INVALID_REQUEST", 400, "allocations entries must be objects")
        if not isinstance(a.get("lot_id"), str):
            fail("ERR_INVALID_REQUEST", 400, "allocations.lot_id is required")
        qv = a.get("quantity_lbs")
        if isinstance(qv, bool) or not isinstance(qv, int) or qv < 1:
            fail("ERR_INVALID_REQUEST", 400, "allocations.quantity_lbs must be an integer >= 1")
    require_role(role, "SalesManager")
    order, plant, contract = _order_ctx(oid)
    lots = [get_or_404("lots", a["lot_id"], "ERR_LOT_NOT_FOUND") for a in allocations]
    posture_gate(plant, "op")
    if order["status"] != "PRICED":
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be PRICED to confirm")
    # product spec safety (priority 10) before fiscal checks
    for lot in lots:
        if not lot_meets_spec(lot, contract):
            fail("ERR_SPEC_BELOW_CONTRACT_MIN", 422,
                 "An allocated lot fails the contract specification")
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract must be ACTIVE")
    # allocation sums (priority 13): sum equality BEFORE per-lot availability
    if sum(a["quantity_lbs"] for a in allocations) != order["quantity_lbs"]:
        fail("ERR_ALLOCATION_MISMATCH", 422, "Allocations do not sum to the order quantity")
    for a, lot in zip(allocations, lots):
        if a["quantity_lbs"] > available_lbs(lot):
            fail("ERR_INSUFFICIENT_LOT_QUANTITY", 422, "Allocated lot lacks available_lbs")
    # margin floor (priority 17)
    if order["margin_pct"] is None or Decimal(str(order["margin_pct"])) < Decimal(str(contract["margin_floor_pct"])):
        fail("ERR_MARGIN_FLOOR_BREACH", 402, "Order margin is below the contract floor")
    order["allocations"] = [{"lot_id": a["lot_id"], "quantity_lbs": a["quantity_lbs"]}
                            for a in allocations]
    for a, lot in zip(allocations, lots):
        lot["allocated_lbs"] += a["quantity_lbs"]
        touch(lot)
    order["status"] = "CONFIRMED"
    touch(order)
    return ok(view(order), 200)


@bp.post("/rendering/sales-orders/<oid>/deallocate")
def deallocate_order(oid):
    uid, role = caller()
    require_role(role, "SalesManager")
    order, plant, contract = _order_ctx(oid)
    posture_gate(plant, "op")
    if order["status"] != "CONFIRMED":
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be CONFIRMED to deallocate")
    release_order_allocations(order)
    order["status"] = "PRICED"
    touch(order)
    return ok(view(order), 200)


@bp.post("/rendering/sales-orders/<oid>/ship")
def ship_order(oid):
    uid, role = caller()
    b = body_json()
    vehicle_id = v_str(b, "vehicle_id")
    require_role(role, "RouteDispatcher")
    order, plant, contract = _order_ctx(oid)
    vehicle = get_or_404("vehicles", vehicle_id, "ERR_VEHICLE_NOT_FOUND")
    posture_gate(plant, "op")
    if order["status"] != "CONFIRMED":
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be CONFIRMED to ship")
    if vehicle["sanitation_status"] != "SANITIZED":
        fail("ERR_VEHICLE_NOT_SANITIZED", 409, "Vehicle must be SANITIZED")
    if vehicle["duty_class"] not in ("FINISHED_PRODUCT", "DUAL"):
        fail("ERR_VEHICLE_DUTY_MISMATCH", 409, "Vehicle duty must be FINISHED_PRODUCT or DUAL")
    order["shipped_vehicle_id"] = vehicle_id
    order["status"] = "SHIPPED"
    touch(order)
    vehicle["sanitation_status"] = "DIRTY"
    vehicle["completed_trip_count"] += 1
    touch(vehicle)
    for a in order["allocations"]:
        lot = db.STORES["lots"].get(a["lot_id"])
        if lot is None:
            continue
        # shipped pounds leave the lot: quantity and allocation both drop,
        # so available_lbs (= quantity - allocated) is unchanged by shipment
        lot["quantity_lbs"] -= a["quantity_lbs"]
        lot["allocated_lbs"] -= a["quantity_lbs"]
        if available_lbs(lot) == 0 and lot["allocated_lbs"] == 0 and lot["status"] == "RELEASED":
            lot["status"] = "DEPLETED"
        touch(lot)
    contract["delivered_volume_lbs"] += order["quantity_lbs"]
    touch(contract)
    return ok(view(order), 200)


@bp.post("/rendering/sales-orders/<oid>/invoice")
def invoice_order(oid):
    uid, role = caller()
    require_role(role, "FinanceAnalyst")
    order, plant, contract = _order_ctx(oid)
    posture_gate(plant, "op")
    if order["status"] != "SHIPPED":
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be SHIPPED to invoice")
    settlement = current_settlement(plant)
    if settlement is None or settlement["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_PERIOD_CLOSED", 409, "Current period settlement is not OPEN/REOPENED")
    settlement["product_revenue_cents"] += order["net_amount_cents"]
    touch(settlement)
    order["status"] = "INVOICED"
    touch(order)
    return ok(view(order), 200)


@bp.post("/rendering/sales-orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = caller()
    require_role(role, "SalesManager")
    order, plant, contract = _order_ctx(oid)
    posture_gate(plant, "op")
    if order["status"] not in ("DRAFT", "PRICED", "CONFIRMED"):
        fail("ERR_ORDER_INVALID_STATE", 409, "Order must be DRAFT, PRICED or CONFIRMED to cancel")
    if order["status"] == "CONFIRMED":
        release_order_allocations(order)
    order["status"] = "CANCELLED"
    touch(order)
    return ok(view(order), 200)


# ---------------- price index entries ----------------

@bp.post("/rendering/price-index-entries")
def create_index_entry():
    uid, role = caller()
    b = body_json()
    plant_id = v_str(b, "plant_id")
    index_product = v_enum(b, "index_product", INDEX_PRODUCTS)
    effective_date = v_date(b, "effective_date")
    price = v_int(b, "price_cents_per_lb", minv=1)
    source = v_enum(b, "source", INDEX_SOURCES)
    require_role(role, "FinanceAnalyst")
    plant = get_or_404("plants", plant_id, "ERR_PLANT_NOT_FOUND")
    posture_gate(plant, "op")
    for e in db.STORES["index_entries"].values():
        if (e["plant_id"] == plant_id and e["index_product"] == index_product
                and e["effective_date"] == effective_date):
            fail("ERR_DUPLICATE_INDEX_ENTRY", 409,
                 "An entry already exists for this plant, product and effective date")
    entry = {
        "plant_id": plant_id,
        "index_product": index_product,
        "effective_date": effective_date,
        "price_cents_per_lb": price,
        "source": source,
        "published_by": uid,
    }
    stamp_new(entry, common=False)
    db.STORES["index_entries"][entry["id"]] = entry
    return ok(view(entry), 201)


@bp.get("/rendering/price-index-entries")
def list_index_entries():
    caller()
    items = sorted_items("index_entries", {
        "plant_id": request.args.get("plant_id"),
        "index_product": request.args.get("index_product"),
    })
    return paginate(items)


@bp.get("/rendering/price-index-entries/<eid>")
def get_index_entry(eid):
    caller()
    return ok(view(get_or_404("index_entries", eid, "ERR_INDEX_ENTRY_NOT_FOUND")), 200)
