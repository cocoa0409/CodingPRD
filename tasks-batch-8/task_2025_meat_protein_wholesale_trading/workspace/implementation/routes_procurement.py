"""Purchase orders, inventory lots, and fabrication batches
(PRD sections 3.3, 3.4, 3.5)."""

from datetime import date

from flask import Blueprint, request

from store import TABLES, clock_now
from helpers import (
    auth, success, err, get_body, req_str, req_num, req_positive_num,
    req_positive_int, req_date, parse_iso_date, paginate, sorted_by_created,
    stamp_new, touch, path_get, require_ref, find, num_out, dec, q2,
    recompute_warehouse, lot_age_days, lot_public, make_lot, recompute_lot_value,
    cutout_at_booking,
)

bp = Blueprint("procurement", __name__)

ADMIN = ["DeskAdmin"]
TRADER = ["Trader"]
GRADER = ["QualityGrader"]
WAREHOUSE = ["WarehouseOperator"]
ALL = ["DeskAdmin", "Trader", "RiskOfficer", "QualityGrader",
       "WarehouseOperator", "ClaimsAdjuster", "CustomerRep"]


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

def po_public(p):
    return {
        "id": p["id"],
        "po_number": p["po_number"],
        "supplier_id": p["supplier_id"],
        "product_id": p["product_id"],
        "ordered_weight_lbs": num_out(p["ordered_weight_lbs"]),
        "contract_price_per_cwt_cents": p["contract_price_per_cwt_cents"],
        "required_delivery_date": p["required_delivery_date"],
        "received_weight_lbs": num_out(p["received_weight_lbs"]),
        "estimated_cutout_value_cents": p["estimated_cutout_value_cents"],
        "actual_cutout_value_cents": p["actual_cutout_value_cents"],
        "status": p["status"],
        "cancel_reason": p["cancel_reason"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/api/purchase-orders", methods=["POST"])
def create_po():
    auth(TRADER)
    body = get_body()
    po_number = req_str(body, "po_number")
    supplier_id = req_str(body, "supplier_id")
    product_id = req_str(body, "product_id")
    weight = req_positive_num(body, "ordered_weight_lbs")
    price_cwt = req_positive_int(body, "contract_price_per_cwt_cents")
    delivery = req_date(body, "required_delivery_date")
    # Body FK existence (priority 6).
    supplier = require_ref("suppliers", supplier_id, "supplier_id")
    product = require_ref("products", product_id, "product_id")
    # Cross-entity state (priority 8): supplier must be ACTIVE.
    if supplier["status"] != "ACTIVE":
        err("ERR_SUPPLIER_SUSPENDED", 409, "Supplier is SUSPENDED")
    # Uniqueness (priority 10).
    for p in TABLES["purchase_orders"].values():
        if p["po_number"] == po_number:
            err("ERR_DUPLICATE_CODE", 409, f"po_number already exists: {po_number}")
    # Kind compatibility (priority 13).
    if product["kind"] not in ("CARCASS", "PRIMAL"):
        err("ERR_PRODUCT_KIND_MISMATCH", 422,
            "Purchase order product kind must be CARCASS or PRIMAL")
    rec = {
        "po_number": po_number,
        "supplier_id": supplier_id,
        "product_id": product_id,
        "ordered_weight_lbs": q2(weight),
        "contract_price_per_cwt_cents": price_cwt,
        "required_delivery_date": delivery,
        "received_weight_lbs": None,
        "estimated_cutout_value_cents": cutout_at_booking(product, q2(weight)),
        "actual_cutout_value_cents": None,
        "status": "BOOKED",
        "cancel_reason": None,
    }
    stamp_new(rec)
    TABLES["purchase_orders"][rec["id"]] = rec
    return success(po_public(rec), code=201)


@bp.route("/api/purchase-orders", methods=["GET"])
def list_pos():
    auth(ALL)
    items = sorted_by_created(TABLES["purchase_orders"].values())
    supplier_id = request.args.get("supplier_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if supplier_id is not None:
        items = [p for p in items if p["supplier_id"] == supplier_id]
    if product_id is not None:
        items = [p for p in items if p["product_id"] == product_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([po_public(p) for p in page], response_type="array",
                   pagination=meta)


@bp.route("/api/purchase-orders/<poId>", methods=["GET"])
def get_po(poId):
    auth(ALL)
    p = path_get("purchase_orders", poId, "ERR_PURCHASE_ORDER_NOT_FOUND")
    return success(po_public(p))


@bp.route("/api/purchase-orders/<poId>/receive", methods=["POST"])
def receive_po(poId):
    auth(WAREHOUSE)
    body = get_body()
    weight = req_positive_num(body, "received_weight_lbs")
    warehouse_id = req_str(body, "warehouse_id")
    lot_code = req_str(body, "lot_code")
    production_date = req_date(body, "production_date")
    # Path existence (priority 5).
    po = path_get("purchase_orders", poId, "ERR_PURCHASE_ORDER_NOT_FOUND")
    # Body FK existence (priority 6).
    warehouse = require_ref("warehouses", warehouse_id, "warehouse_id")
    # Target state (priority 7).
    if po["status"] != "BOOKED":
        err("ERR_PO_NOT_BOOKED", 409, "Purchase order must be BOOKED to receive")
    # Cross-entity state (priority 8): supplier must be ACTIVE.
    supplier = find("suppliers", po["supplier_id"])
    if supplier is None or supplier["status"] != "ACTIVE":
        err("ERR_SUPPLIER_SUSPENDED", 409, "Supplier is SUSPENDED")
    # Uniqueness (priority 10): lot_code.
    for lot in TABLES["inventory_lots"].values():
        if lot["lot_code"] == lot_code:
            err("ERR_DUPLICATE_CODE", 409, f"lot_code already exists: {lot_code}")
    # Warehouse capacity (priority 11).
    weight = q2(weight)
    if dec(warehouse["occupied_lbs"]) + weight > dec(warehouse["capacity_lbs"]):
        err("ERR_WAREHOUSE_CAPACITY_EXCEEDED", 409,
            "occupied_lbs + received_weight_lbs exceeds capacity_lbs")
    # Temporal (priority 12): production date not future, age within shelf life.
    product = find("products", po["product_id"])
    prod = parse_iso_date(production_date, "production_date")
    today = clock_now().date()
    if prod > today:
        err("ERR_PRODUCTION_DATE_INVALID", 422,
            "production_date lies in the future")
    if (today - prod).days > product["shelf_life_days"]:
        err("ERR_PRODUCTION_DATE_INVALID", 422,
            "Lot age at receiving exceeds product shelf_life_days")
    # Effects: create the lot, advance the PO, recompute occupancy.
    make_lot(lot_code=lot_code, product_id=po["product_id"],
             warehouse_id=warehouse["id"], weight_lbs=weight,
             production_date=production_date, po_id=po["id"],
             status="IN_INSPECTION")
    po["received_weight_lbs"] = weight
    po["status"] = "RECEIVED"
    touch(po)
    recompute_warehouse(warehouse["id"])
    return success(po_public(po))


@bp.route("/api/purchase-orders/<poId>/cancel", methods=["POST"])
def cancel_po(poId):
    auth(TRADER)
    po = path_get("purchase_orders", poId, "ERR_PURCHASE_ORDER_NOT_FOUND")
    if po["status"] != "BOOKED":
        err("ERR_PO_NOT_BOOKED", 409, "Only a BOOKED purchase order may be cancelled")
    po["status"] = "CANCELLED"
    po["cancel_reason"] = "MANUAL"
    touch(po)
    return success(po_public(po))


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

@bp.route("/api/inventory-lots", methods=["GET"])
def list_lots():
    auth(ALL)
    items = sorted_by_created(TABLES["inventory_lots"].values())
    for param, field in (("warehouse_id", "warehouse_id"),
                         ("product_id", "product_id"),
                         ("status", "status"),
                         ("po_id", "po_id"),
                         ("parent_lot_id", "parent_lot_id"),
                         ("fabrication_batch_id", "fabrication_batch_id")):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l[field] == v]
    page, meta = paginate(items)
    return success([lot_public(l) for l in page], response_type="array",
                   pagination=meta)


@bp.route("/api/inventory-lots/<lotId>", methods=["GET"])
def get_lot(lotId):
    auth(ALL)
    lot = path_get("inventory_lots", lotId, "ERR_LOT_NOT_FOUND")
    return success(lot_public(lot))


@bp.route("/api/inventory-lots/<lotId>/inspect", methods=["POST"])
def inspect_lot(lotId):
    auth(GRADER)
    body = get_body()
    measured = req_num(body, "measured_fat_pct")
    lot = path_get("inventory_lots", lotId, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "IN_INSPECTION":
        err("ERR_LOT_NOT_IN_INSPECTION", 409, "Lot must be IN_INSPECTION to inspect")
    product = find("products", lot["product_id"])
    if product["kind"] == "CARCASS" or product["max_fat_pct"] is None:
        compliant = True
    else:
        compliant = measured <= dec(product["max_fat_pct"])
    lot["measured_fat_pct"] = measured
    lot["spec_compliant"] = compliant
    if compliant:
        lot["status"] = "AVAILABLE"
        # If a grade has already been recorded, recompute the market value.
        recompute_lot_value(lot)
    else:
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = "SPEC_NONCOMPLIANCE"
    touch(lot)
    recompute_warehouse(lot["warehouse_id"])
    return success(lot_public(lot))


@bp.route("/api/inventory-lots/<lotId>/quarantine", methods=["POST"])
def quarantine_lot(lotId):
    auth(GRADER)
    lot = path_get("inventory_lots", lotId, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "AVAILABLE":
        err("ERR_LOT_NOT_AVAILABLE", 409, "Only an AVAILABLE lot may be quarantined")
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = "USDA_HOLD"
    touch(lot)
    recompute_warehouse(lot["warehouse_id"])
    return success(lot_public(lot))


@bp.route("/api/inventory-lots/<lotId>/release", methods=["POST"])
def release_lot(lotId):
    auth(GRADER)
    lot = path_get("inventory_lots", lotId, "ERR_LOT_NOT_FOUND")
    if lot["status"] != "QUARANTINED":
        err("ERR_INVALID_STATE", 409, "Only a QUARANTINED lot may be released")
    product = find("products", lot["product_id"])
    if lot_age_days(lot) > product["shelf_life_days"]:
        err("ERR_LOT_EXPIRED", 409, "Lot age exceeds product shelf_life_days")
    lot["status"] = "AVAILABLE"
    lot["quarantine_reason"] = None
    recompute_lot_value(lot)
    touch(lot)
    recompute_warehouse(lot["warehouse_id"])
    return success(lot_public(lot))


# ---------------------------------------------------------------------------
# Fabrication batches
# ---------------------------------------------------------------------------

def batch_public(b):
    return {
        "id": b["id"],
        "input_lot_id": b["input_lot_id"],
        "loss_lbs": num_out(b["loss_lbs"]),
        "outputs": [
            {"product_id": o["product_id"], "weight_lbs": num_out(o["weight_lbs"])}
            for o in b["outputs"]
        ],
        "total_output_weight_lbs": num_out(b["total_output_weight_lbs"]),
        "yield_efficiency_pct": num_out(b["yield_efficiency_pct"]),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.route("/api/fabrication-batches", methods=["POST"])
def create_batch():
    auth(WAREHOUSE)
    body = get_body()
    input_lot_id = req_str(body, "input_lot_id")
    loss = req_num(body, "loss_lbs")
    if loss < 0:
        err("ERR_INVALID_REQUEST", 400, "loss_lbs must be non-negative")
    outputs_raw = body.get("outputs")
    if not isinstance(outputs_raw, list) or not outputs_raw:
        err("ERR_INVALID_REQUEST", 400, "outputs must be a non-empty array")
    outputs = []
    for entry in outputs_raw:
        if not isinstance(entry, dict):
            err("ERR_INVALID_REQUEST", 400, "outputs entries must be objects")
        pid = entry.get("product_id")
        if not isinstance(pid, str):
            err("ERR_INVALID_REQUEST", 400, "outputs[].product_id must be a string")
        w = entry.get("weight_lbs")
        try:
            w = dec(w)
        except Exception:
            err("ERR_INVALID_REQUEST", 400, "outputs[].weight_lbs must be a number")
        if w <= 0:
            err("ERR_INVALID_REQUEST", 400, "outputs[].weight_lbs must be positive")
        outputs.append({"product_id": pid, "weight_lbs": q2(w)})
    # Body FK existence (priority 6).
    lot = require_ref("inventory_lots", input_lot_id, "input_lot_id")
    for o in outputs:
        require_ref("products", o["product_id"], "outputs[].product_id")
    # State: input lot must be AVAILABLE.
    if lot["status"] != "AVAILABLE":
        err("ERR_LOT_NOT_AVAILABLE", 409, "Fabrication input lot must be AVAILABLE")
    # Kind compatibility (priority 13): input must be a carcass; every output
    # must be covered by a yield spec from the input product.
    input_product = find("products", lot["product_id"])
    if input_product is None or input_product["kind"] != "CARCASS":
        err("ERR_PRODUCT_KIND_MISMATCH", 422,
            "Fabrication input lot product must be a CARCASS")
    for o in outputs:
        covered = any(
            ys["carcass_product_id"] == lot["product_id"]
            and ys["output_product_id"] == o["product_id"]
            for ys in TABLES["yield_specs"].values())
        if not covered:
            err("ERR_PRODUCT_KIND_MISMATCH", 422,
                f"No yield spec covers output product {o['product_id']} "
                f"from carcass {lot['product_id']}")
    total = q2(sum((o["weight_lbs"] for o in outputs), dec(0)))
    consumed = dec(lot["current_weight_lbs"])
    efficiency = q2(total / consumed * dec(100)) if consumed > 0 else dec(0)
    rec = {
        "input_lot_id": lot["id"],
        "loss_lbs": q2(loss),
        "outputs": outputs,
        "total_output_weight_lbs": total,
        "yield_efficiency_pct": efficiency,
        "status": "DRAFT",
        "_input_weight_at_post": None,
    }
    stamp_new(rec)
    TABLES["fabrication_batches"][rec["id"]] = rec
    return success(batch_public(rec), code=201)


@bp.route("/api/fabrication-batches", methods=["GET"])
def list_batches():
    auth(ALL)
    items = sorted_by_created(TABLES["fabrication_batches"].values())
    input_lot_id = request.args.get("input_lot_id")
    status = request.args.get("status")
    if input_lot_id is not None:
        items = [b for b in items if b["input_lot_id"] == input_lot_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    return success([batch_public(b) for b in page], response_type="array",
                   pagination=meta)


@bp.route("/api/fabrication-batches/<batchId>", methods=["GET"])
def get_batch(batchId):
    auth(ALL)
    b = path_get("fabrication_batches", batchId, "ERR_FABRICATION_BATCH_NOT_FOUND")
    return success(batch_public(b))


@bp.route("/api/fabrication-batches/<batchId>/post", methods=["POST"])
def post_batch(batchId):
    auth(WAREHOUSE)
    b = path_get("fabrication_batches", batchId, "ERR_FABRICATION_BATCH_NOT_FOUND")
    if b["status"] != "DRAFT":
        err("ERR_BATCH_NOT_DRAFT", 409, "Only a DRAFT batch may be posted")
    lot = find("inventory_lots", b["input_lot_id"])
    if lot is None:
        err("ERR_REFERENCE_NOT_FOUND", 422, "Input lot no longer exists")
    if lot["status"] != "AVAILABLE":
        err("ERR_LOT_NOT_AVAILABLE", 409, "Fabrication input lot must be AVAILABLE")
    consumed = dec(lot["current_weight_lbs"])
    total = dec(b["total_output_weight_lbs"])
    # Mass balance (priority 10): outputs + loss == input current weight, exact.
    if total + dec(b["loss_lbs"]) != consumed:
        err("ERR_MASS_BALANCE_VIOLATION", 422,
            "total_output_weight_lbs + loss_lbs must equal the input lot's "
            "current_weight_lbs exactly")
    # Capacity (priority 11): output lots land in the same cold store.
    warehouse = find("warehouses", lot["warehouse_id"])
    if warehouse is not None and \
            dec(warehouse["occupied_lbs"]) + total > dec(warehouse["capacity_lbs"]):
        err("ERR_WAREHOUSE_CAPACITY_EXCEEDED", 409,
            "occupied_lbs + output weight exceeds capacity_lbs")
    # Consume the input lot.
    b["_input_weight_at_post"] = consumed
    lot["current_weight_lbs"] = q2(dec(0))
    lot["status"] = "DEPLETED"
    touch(lot)
    # Create one output lot per entry; route by yield band.
    import uuid as _uuid
    for o in b["outputs"]:
        spec = None
        for ys in sorted_by_created(TABLES["yield_specs"].values()):
            if ys["carcass_product_id"] == lot["product_id"] and \
                    ys["output_product_id"] == o["product_id"]:
                spec = ys
                break
        actual_pct = (o["weight_lbs"] / consumed * dec(100)) if consumed > 0 else dec(0)
        in_band = spec is not None and \
            dec(spec["min_yield_pct"]) <= actual_pct <= dec(spec["max_yield_pct"])
        make_lot(
            lot_code=f"FAB-{_uuid.uuid4().hex[:12].upper()}",
            product_id=o["product_id"],
            warehouse_id=lot["warehouse_id"],
            weight_lbs=o["weight_lbs"],
            production_date=lot["production_date"],
            parent_lot_id=lot["id"],
            fabrication_batch_id=b["id"],
            status="IN_INSPECTION" if in_band else "QUARANTINED",
            quarantine_reason=None if in_band else "YIELD_OUT_OF_BAND",
        )
    # Recompute batch totals against the consumed input weight.
    b["total_output_weight_lbs"] = q2(total)
    b["yield_efficiency_pct"] = q2(total / consumed * dec(100)) if consumed > 0 else dec(0)
    b["status"] = "POSTED"
    touch(b)
    recompute_warehouse(lot["warehouse_id"])
    return success(batch_public(b))


@bp.route("/api/fabrication-batches/<batchId>/void", methods=["POST"])
def void_batch(batchId):
    auth(ADMIN)
    b = path_get("fabrication_batches", batchId, "ERR_FABRICATION_BATCH_NOT_FOUND")
    if b["status"] == "DRAFT":
        b["status"] = "VOIDED"
        touch(b)
        return success(batch_public(b))
    if b["status"] != "POSTED":
        err("ERR_BATCH_NOT_DRAFT", 409, "Batch is not in a voidable state")
    outputs = [l for l in sorted_by_created(TABLES["inventory_lots"].values())
               if l["fabrication_batch_id"] == b["id"]]
    for out in outputs:
        if dec(out["current_weight_lbs"]) != dec(out["received_weight_lbs"]):
            err("ERR_BATCH_NOT_VOIDABLE", 409,
                "A POSTED batch with a drawn-down output lot cannot be voided")
    # Cascade link 1: output lots -> DEPLETED at zero weight.
    for out in outputs:
        out["current_weight_lbs"] = q2(dec(0))
        out["status"] = "DEPLETED"
        touch(out)
    # Cascade link 2: restore the input lot to its pre-post weight.
    lot = find("inventory_lots", b["input_lot_id"])
    if lot is not None:
        restored = b["_input_weight_at_post"]
        if restored is None:
            restored = q2(dec(b["total_output_weight_lbs"]) + dec(b["loss_lbs"]))
        lot["current_weight_lbs"] = q2(dec(restored))
        lot["status"] = "AVAILABLE"
        touch(lot)
    b["status"] = "VOIDED"
    touch(b)
    if lot is not None:
        recompute_warehouse(lot["warehouse_id"])
    return success(batch_public(b))
