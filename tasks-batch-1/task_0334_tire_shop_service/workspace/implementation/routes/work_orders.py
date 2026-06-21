"""Work-order routes — the core pricing engine + parallel state machine.

PRD §3.2 (build/price), §3.7 (lifecycle), §2.7 (parallel state), §2.9 (OCC).
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_FITMENT_NOT_APPROVED,
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LINE_TYPE_FIELD_MISMATCH,
    ERR_PAYMENT_REQUIRED,
    ERR_STALE_VERSION,
    ERR_STALE_WORK_ORDER_VERSION,
    ERR_VEHICLE_NOT_OWNED,
)
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import SERVICE_RATE_CENTS
from services.cascades import (
    apply_approval,
    apply_cancellation,
    fitment_approved,
    has_open_or_received_special_order,
    non_void_lines,
    order_lines,
)
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    optional_bool,
    optional_int,
    require_enum,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("work_orders", __name__)

LINE_TYPES = {"TIRE", "MOUNT_BALANCE", "ROTATION", "TPMS_SERVICE", "ALIGNMENT"}
FULFILLMENT_STATUSES = {"DRAFT", "APPROVED", "IN_SERVICE", "COMPLETED", "CANCELLED"}
PAYMENT_STATUSES = {"UNPAID", "AUTHORIZED", "PAID", "REFUNDED"}


# ---------------------------------------------------------------------------
# Work order CRUD
# ---------------------------------------------------------------------------


@bp.post("/work-orders")
def create_work_order():
    require_auth(["ServiceAdvisor", "Customer"])()
    body = get_json_body()
    require_fields(body, ["customer_id", "vehicle_id"])
    customer_id = require_string(body["customer_id"], "customer_id")
    vehicle_id = require_string(body["vehicle_id"], "vehicle_id")
    store_credit_applied_cents = optional_int(
        body.get("store_credit_applied_cents"), "store_credit_applied_cents", 0,
        min_value=0,
    )

    with db.mutation_lock:
        lookup_fk_or_404(db.customers, customer_id, "Customer")
        vehicle = lookup_fk_or_404(db.vehicles, vehicle_id, "Vehicle")
        if vehicle["customer_id"] != customer_id:
            raise APIError(ERR_VEHICLE_NOT_OWNED, 422,
                           "vehicle_id does not belong to customer_id")
        order = {
            "customer_id": customer_id,
            "vehicle_id": vehicle_id,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNPAID",
            "store_credit_applied_cents": store_credit_applied_cents,
            "parts_subtotal_cents": 0,
            "service_subtotal_cents": 0,
            "disposal_fee_cents": 0,
            "road_hazard_premium_cents": 0,
            "tax_cents": 0,
            "total_due_cents": 0,
        }
        db.stamp_common(order)
        db.work_orders[order["id"]] = order
        return ok_object(order, 201)


@bp.get("/work-orders/<wid>")
def get_work_order(wid: str):
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    return ok_object(order, 200)


@bp.get("/work-orders")
def list_work_orders():
    require_auth(["ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.work_orders.values())
    if "customer_id" in request.args:
        items = [o for o in items if o["customer_id"] == request.args["customer_id"]]
    if "vehicle_id" in request.args:
        items = [o for o in items if o["vehicle_id"] == request.args["vehicle_id"]]
    if "fulfillment_status" in request.args:
        items = [o for o in items
                 if o["fulfillment_status"] == request.args["fulfillment_status"]]
    if "payment_status" in request.args:
        items = [o for o in items
                 if o["payment_status"] == request.args["payment_status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Work order lines
# ---------------------------------------------------------------------------


@bp.post("/work-orders/<wid>/lines")
def add_line(wid: str):
    require_auth(["ServiceAdvisor", "Customer"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    body = get_json_body()
    require_fields(body, ["line_type", "quantity", "expected_work_order_version"])
    line_type = require_enum(body["line_type"], LINE_TYPES, "line_type")
    quantity = require_int(body["quantity"], "quantity", min_value=1)
    expected = require_int(body["expected_work_order_version"],
                           "expected_work_order_version")
    road_hazard_opted = optional_bool(body.get("road_hazard_opted"),
                                      "road_hazard_opted", False)
    tire_model_id = body.get("tire_model_id")

    with db.mutation_lock:
        # State gate (priority 7): lines may be added only while DRAFT.
        if order["fulfillment_status"] != "DRAFT":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Lines may be added only to a DRAFT order")

        # line_type / tire_model_id coherence (priority 6).
        if line_type == "TIRE":
            if not tire_model_id:
                raise APIError(ERR_LINE_TYPE_FIELD_MISMATCH, 422,
                               "TIRE line requires tire_model_id")
        else:
            if tire_model_id is not None:
                raise APIError(ERR_LINE_TYPE_FIELD_MISMATCH, 422,
                               "non-TIRE line must omit tire_model_id")

        # FK existence (priority 4) for the tire model when present.
        if line_type == "TIRE":
            model = lookup_fk_or_404(db.tire_models, tire_model_id, "TireModel")
            unit_price = model["unit_price_cents"]
        else:
            road_hazard_opted = False  # forced false for non-TIRE lines
            unit_price = SERVICE_RATE_CENTS[line_type]

        # OCC (priority 17): expected version must match the order's version.
        if expected != order["version"]:
            raise APIError(ERR_STALE_WORK_ORDER_VERSION, 412,
                           "expected_work_order_version does not match")

        line = {
            "work_order_id": order["id"],
            "line_type": line_type,
            "tire_model_id": tire_model_id if line_type == "TIRE" else None,
            "quantity": quantity,
            "unit_price_cents_snapshot": unit_price,
            "road_hazard_opted": road_hazard_opted,
            "extended_cents": 0,
            "line_status": "PENDING",
        }
        db.stamp_common(line)
        db.work_order_lines[line["id"]] = line
        # PRD §2.9: a work order's version is bumped only at approval and at
        # cancellation, not at line-add. The expected_work_order_version guard
        # exists so a line-add fails if the order has already advanced past
        # DRAFT (approved/cancelled). Adding a line refreshes updated_at but
        # must not increment the order's version.
        db.touch(order)
        return ok_object(line, 201)


@bp.get("/work-orders/<wid>/lines")
def list_order_lines(wid: str):
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    limit, offset = paginate_params(request.args)
    items = order_lines(wid)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/work-order-lines/<lid>")
def get_line(lid: str):
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    line = lookup_path_or_404(db.work_order_lines, lid, "WorkOrderLine")
    return ok_object(line, 200)


@bp.get("/work-order-lines")
def list_lines():
    require_auth(["ServiceAdvisor", "Customer", "Technician"])()
    limit, offset = paginate_params(request.args)
    items = list(db.work_order_lines.values())
    if "work_order_id" in request.args:
        items = [l for l in items
                 if l["work_order_id"] == request.args["work_order_id"]]
    if "tire_model_id" in request.args:
        items = [l for l in items
                 if l.get("tire_model_id") == request.args["tire_model_id"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Lifecycle transitions — fulfillment axis
# ---------------------------------------------------------------------------


@bp.post("/work-orders/<wid>/approve")
def approve(wid: str):
    require_auth(["ServiceAdvisor"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    body = get_json_body()
    require_fields(body, ["expected_work_order_version"])
    expected = require_int(body["expected_work_order_version"],
                           "expected_work_order_version")

    with db.mutation_lock:
        # State (priority 7): must be DRAFT.
        if order["fulfillment_status"] != "DRAFT":
            raise APIError(ERR_INVALID_STATE, 409, "Order is not DRAFT")
        # Must have >= 1 line.
        lines = non_void_lines(order["id"])
        if len(lines) < 1:
            raise APIError(ERR_INVALID_STATE, 409, "Order has no lines")

        # Fitment guard (priority 8) before pricing.
        for line in lines:
            if line["line_type"] == "TIRE":
                if not fitment_approved(order["vehicle_id"], line["tire_model_id"]):
                    raise APIError(ERR_FITMENT_NOT_APPROVED, 422,
                                   "TIRE line tire model not approved for vehicle")

        # OCC (priority 17): generic stale-version on approve.
        if expected != order["version"]:
            raise APIError(ERR_STALE_VERSION, 412,
                           "expected_work_order_version does not match")

        # Stock guard (priority 13): each TIRE line stockable or sourced.
        for line in lines:
            if line["line_type"] != "TIRE":
                continue
            model = db.tire_models[line["tire_model_id"]]
            if model["stock_qty"] >= line["quantity"]:
                continue
            if has_open_or_received_special_order(line["id"]):
                continue
            raise APIError(ERR_INSUFFICIENT_STOCK, 422,
                           "TIRE line cannot be stocked or sourced")

        # All guards pass — run pricing + side effects atomically.
        apply_approval(order)
        order["fulfillment_status"] = "APPROVED"
        db.bump(order)
        return ok_object(order, 200)


@bp.post("/work-orders/<wid>/start-service")
def start_service(wid: str):
    require_auth(["Technician"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    with db.mutation_lock:
        if order["fulfillment_status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE, 409, "Order is not APPROVED")
        checked_in = any(
            a["work_order_id"] == order["id"] and a["status"] == "CHECKED_IN"
            for a in db.appointments.values()
        )
        if not checked_in:
            raise APIError(ERR_INVALID_STATE, 409,
                           "No CHECKED_IN appointment for this order")
        order["fulfillment_status"] = "IN_SERVICE"
        db.bump(order)
        return ok_object(order, 200)


@bp.post("/work-orders/<wid>/complete")
def complete(wid: str):
    require_auth(["Technician"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    with db.mutation_lock:
        if order["fulfillment_status"] != "IN_SERVICE":
            raise APIError(ERR_INVALID_STATE, 409, "Order is not IN_SERVICE")
        # Payment gate (priority 16).
        if order["payment_status"] not in ("AUTHORIZED", "PAID"):
            raise APIError(ERR_PAYMENT_REQUIRED, 402,
                           "Order must be AUTHORIZED or PAID to complete")
        # Drive the linked CHECKED_IN appointment to COMPLETED.
        for a in db.appointments.values():
            if a["work_order_id"] == order["id"] and a["status"] == "CHECKED_IN":
                a["status"] = "COMPLETED"
                db.bump(a)
        # Auto-capture an authorized payment.
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "PAID"
        order["fulfillment_status"] = "COMPLETED"
        db.bump(order)
        return ok_object(order, 200)


@bp.post("/work-orders/<wid>/cancel")
def cancel(wid: str):
    require_auth(["ServiceAdvisor"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    body = get_json_body()
    require_fields(body, ["expected_work_order_version"])
    expected = require_int(body["expected_work_order_version"],
                           "expected_work_order_version")
    with db.mutation_lock:
        if order["fulfillment_status"] not in ("DRAFT", "APPROVED"):
            raise APIError(ERR_INVALID_STATE, 409,
                           "Only DRAFT or APPROVED orders can be cancelled")
        # APPROVED order cannot be cancelled once an appointment is CHECKED_IN.
        if order["fulfillment_status"] == "APPROVED":
            for a in db.appointments.values():
                if (a["work_order_id"] == order["id"]
                        and a["status"] == "CHECKED_IN"):
                    raise APIError(ERR_INVALID_STATE, 409,
                                   "Cannot cancel: vehicle is checked in")
        # OCC (priority 17).
        if expected != order["version"]:
            raise APIError(ERR_STALE_VERSION, 412,
                           "expected_work_order_version does not match")

        apply_cancellation(order)
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "REFUNDED"
        order["fulfillment_status"] = "CANCELLED"
        db.bump(order)
        return ok_object(order, 200)


# ---------------------------------------------------------------------------
# Lifecycle transitions — payment axis
# ---------------------------------------------------------------------------


@bp.post("/work-orders/<wid>/authorize-payment")
def authorize_payment(wid: str):
    require_auth(["ServiceAdvisor"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    with db.mutation_lock:
        if order["fulfillment_status"] != "APPROVED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "Order must be APPROVED to authorize payment")
        if order["payment_status"] != "UNPAID":
            raise APIError(ERR_INVALID_STATE, 409, "payment_status is not UNPAID")
        order["payment_status"] = "AUTHORIZED"
        db.bump(order)
        return ok_object(order, 200)


@bp.post("/work-orders/<wid>/capture-payment")
def capture_payment(wid: str):
    require_auth(["ServiceAdvisor"])()
    order = lookup_path_or_404(db.work_orders, wid, "WorkOrder")
    with db.mutation_lock:
        if order["payment_status"] != "AUTHORIZED":
            raise APIError(ERR_INVALID_STATE, 409,
                           "payment_status is not AUTHORIZED")
        order["payment_status"] = "PAID"
        db.bump(order)
        return ok_object(order, 200)
