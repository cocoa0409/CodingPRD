"""ProductionOrder endpoints (parallel production_status x fulfillment_status)."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_int, as_number, as_string, body, require
from services import calc, cascade

bp = Blueprint("orders", __name__)

SHIP_METHODS = {"WAREHOUSE", "DROP_SHIP"}


def order_view(o):
    return {
        "id": o["id"],
        "model_id": o["model_id"],
        "retailer_id": o["retailer_id"],
        "destination_state_code": o["destination_state_code"],
        "quantity": o["quantity"],
        "unit_price_cents": o["unit_price_cents"],
        "foam_mass_required_kg": o["foam_mass_required_kg"],
        "ship_method": o["ship_method"],
        "foam_batch_id": o["foam_batch_id"],
        "subtotal_cents": o["subtotal_cents"],
        "compliance_fee_cents": o["compliance_fee_cents"],
        "total_cents": o["total_cents"],
        "production_status": o["production_status"],
        "fulfillment_status": o["fulfillment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        errors.raise_err(errors.ERR_ORDER_NOT_FOUND, "order not found")
    return o


@bp.route("/production-orders", methods=["POST"])
def create_order():
    user_id, role = middleware.require_roles(["PlantManager", "Retailer"])
    data = body()
    model_id = as_string(require(data, "model_id"), "model_id")
    retailer_id = as_string(require(data, "retailer_id"), "retailer_id")
    destination = as_string(require(data, "destination_state_code"), "destination_state_code")
    quantity = as_int(require(data, "quantity"), "quantity")
    if quantity < 1:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "quantity must be >= 1")
    unit_price = as_int(require(data, "unit_price_cents"), "unit_price_cents")
    if unit_price <= 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "unit_price_cents must be > 0")
    foam_mass = as_number(require(data, "foam_mass_required_kg"), "foam_mass_required_kg")
    if calc.dec(foam_mass) <= 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "foam_mass_required_kg must be > 0")
    ship_method = as_enum(require(data, "ship_method"), "ship_method", SHIP_METHODS)
    # body-FK existence
    model = db.models.get(model_id)
    if model is None:
        errors.raise_err(errors.ERR_MODEL_NOT_FOUND, "model not found")
    retailer = db.retailers.get(retailer_id)
    if retailer is None:
        errors.raise_err(errors.ERR_RETAILER_NOT_FOUND, "retailer not found")
    # tier 5: model must be ACTIVE
    if model["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_MODEL_NOT_ACTIVE, "model must be ACTIVE")
    # tier 8: DROP_SHIP gate
    if ship_method == "DROP_SHIP" and not retailer["drop_ship_enabled"]:
        errors.raise_err(errors.ERR_DROPSHIP_NOT_ENABLED, "retailer not drop-ship enabled")
    # tier 10: Retailer callers may only reference their own id
    if role == "Retailer" and retailer_id != user_id:
        errors.raise_err(
            errors.ERR_RETAILER_IDENTITY_MISMATCH,
            "Retailer callers must reference their own retailer_id",
        )
    subtotal, fee, total = calc.order_pricing(quantity, unit_price)
    order = {
        "id": db.new_id(),
        "order_seq": next(db.order_seq),
        "units_made": 0,
        "model_id": model_id,
        "retailer_id": retailer_id,
        "destination_state_code": destination,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "foam_mass_required_kg": foam_mass,
        "ship_method": ship_method,
        "foam_batch_id": None,
        "subtotal_cents": subtotal,
        "compliance_fee_cents": fee,
        "total_cents": total,
        "production_status": "PLANNED",
        "fulfillment_status": "UNFULFILLED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.orders, order)
    return response.success_object(order_view(order), 201)


@bp.route("/production-orders", methods=["GET"])
def list_orders():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.orders.values())
    for param in ("model_id", "retailer_id", "foam_batch_id", "production_status", "fulfillment_status"):
        q = request.args.get(param)
        if q is not None:
            items = [o for o in items if o[param] == q]
    items.sort(key=lambda o: o["_seq"])
    return response.success_list([order_view(o) for o in items])


@bp.route("/production-orders/<orderId>", methods=["GET"])
def get_one_order(orderId):
    middleware.require_roles(middleware.ALL_ROLES)
    o = get_order(orderId)
    return response.success_object(order_view(o))


@bp.route("/production-orders/<orderId>/allocate-materials", methods=["POST"])
def allocate_materials(orderId):
    middleware.require_roles(["LineSupervisor"])
    order = get_order(orderId)
    data = body()
    batch_id = as_string(require(data, "foam_batch_id"), "foam_batch_id")
    batch = db.foam_batches.get(batch_id)
    if batch is None:
        errors.raise_err(errors.ERR_FOAM_BATCH_NOT_FOUND, "foam batch not found")
    # tier 5: order must be PLANNED
    if order["production_status"] != "PLANNED":
        errors.raise_err(errors.ERR_ORDER_NOT_PLANNED, "order must be PLANNED")
    # batch must be CURED
    if batch["status"] != "CURED":
        errors.raise_err(errors.ERR_BATCH_NOT_CURED, "batch must be CURED")
    # tier 11: sufficient foam mass
    if calc.dec(batch["available_mass_kg"]) < calc.dec(order["foam_mass_required_kg"]):
        errors.raise_err(errors.ERR_INSUFFICIENT_FOAM_MASS, "insufficient available foam mass")
    batch["available_mass_kg"] = float(
        calc.dec(batch["available_mass_kg"]) - calc.dec(order["foam_mass_required_kg"])
    )
    batch["reserved_mass_kg"] = float(
        calc.dec(batch["reserved_mass_kg"]) + calc.dec(order["foam_mass_required_kg"])
    )
    cascade.bump(batch)
    order["foam_batch_id"] = batch["id"]
    order["production_status"] = "MATERIAL_ALLOCATED"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/start-production", methods=["POST"])
def start_production(orderId):
    middleware.require_roles(["LineSupervisor"])
    order = get_order(orderId)
    # tier 5
    if order["production_status"] != "MATERIAL_ALLOCATED":
        errors.raise_err(errors.ERR_ORDER_NOT_MATERIAL_ALLOCATED, "order must be MATERIAL_ALLOCATED")
    # tier 6: ACTIVE law label for (model, destination_state)
    if cascade.active_label_for(order["model_id"], order["destination_state_code"]) is None:
        errors.raise_err(errors.ERR_LABEL_NOT_ACTIVE, "no ACTIVE law label for model and state")
    batch = db.foam_batches.get(order["foam_batch_id"])
    required = calc.dec(order["foam_mass_required_kg"])
    batch["reserved_mass_kg"] = float(calc.dec(batch["reserved_mass_kg"]) - required)
    batch["consumed_mass_kg"] = float(calc.dec(batch["consumed_mass_kg"]) + required)
    if (
        calc.dec(batch["available_mass_kg"]) == 0
        and calc.dec(batch["reserved_mass_kg"]) == 0
        and batch["status"] == "CURED"
    ):
        batch["status"] = "CONSUMED"
    cascade.bump(batch)
    order["production_status"] = "IN_PRODUCTION"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/complete-production", methods=["POST"])
def complete_production(orderId):
    middleware.require_roles(["LineSupervisor"])
    order = get_order(orderId)
    if order["production_status"] != "IN_PRODUCTION":
        errors.raise_err(errors.ERR_ORDER_NOT_IN_PRODUCTION, "order must be IN_PRODUCTION")
    label = cascade.active_label_for(order["model_id"], order["destination_state_code"])
    label_id = label["id"] if label is not None else None
    for _ in range(order["quantity"]):
        cascade.manufacture_unit(order, label_id)
    order["production_status"] = "QC_PENDING"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/qc-pass", methods=["POST"])
def qc_pass(orderId):
    middleware.require_roles(["QcInspector"])
    order = get_order(orderId)
    if order["production_status"] != "QC_PENDING":
        errors.raise_err(errors.ERR_ORDER_NOT_QC_PENDING, "order must be QC_PENDING")
    order["production_status"] = "COMPLETE"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/qc-hold", methods=["POST"])
def qc_hold(orderId):
    middleware.require_roles(["QcInspector"])
    order = get_order(orderId)
    if order["production_status"] != "QC_PENDING":
        errors.raise_err(errors.ERR_ORDER_NOT_QC_PENDING, "order must be QC_PENDING")
    order["production_status"] = "QC_HOLD"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/qc-release", methods=["POST"])
def qc_release(orderId):
    middleware.require_roles(["QcInspector"])
    order = get_order(orderId)
    if order["production_status"] != "QC_HOLD":
        errors.raise_err(errors.ERR_ORDER_NOT_QC_HOLD, "order must be QC_HOLD")
    order["production_status"] = "QC_PENDING"
    cascade.bump(order)
    return response.success_object(order_view(order))


@bp.route("/production-orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    middleware.require_roles(["PlantManager"])
    order = get_order(orderId)
    if order["production_status"] not in ("PLANNED", "MATERIAL_ALLOCATED"):
        errors.raise_err(
            errors.ERR_ORDER_NOT_CANCELLABLE,
            "order must be PLANNED or MATERIAL_ALLOCATED",
        )
    if order["production_status"] == "MATERIAL_ALLOCATED":
        batch = db.foam_batches.get(order["foam_batch_id"])
        if batch is not None:
            required = calc.dec(order["foam_mass_required_kg"])
            batch["reserved_mass_kg"] = float(calc.dec(batch["reserved_mass_kg"]) - required)
            batch["available_mass_kg"] = float(calc.dec(batch["available_mass_kg"]) + required)
            cascade.bump(batch)
    order["production_status"] = "CANCELLED"
    cascade.bump(order)
    return response.success_object(order_view(order))
