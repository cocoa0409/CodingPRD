"""The lab: production, QC, the remake cycle, shipment and handover (PRD 3.7)."""
from flask import Blueprint, request

import schema
import store
from auth import authenticate
from envelope import array_response, object_response, paginate
from errors import err
from serializers import dump, dump_all

bp = Blueprint("lab", __name__)

REMAKE_LIMIT = 2


@bp.get("/lab-orders/<lab_id>")
def read_lab_order(lab_id):
    authenticate("LabTechnician", "StoreAssociate", "Customer", "PlatformAdmin")
    rec = schema.get_lab_order(lab_id)
    return object_response(dump("lab_order", rec))


@bp.get("/lab-orders")
def list_lab_orders():
    authenticate("LabTechnician", "StoreAssociate", "PlatformAdmin")
    items = store.ordered(store.lab_orders)
    for field in ("order_id", "shipped_to_store_id", "active_warranty_claim_id", "status"):
        value = request.args.get(field)
        if value:
            items = [lo for lo in items if lo[field] == value]
    window, meta = paginate(items)
    return array_response(dump_all("lab_order", window), meta)


@bp.post("/lab-orders/<lab_id>/start")
def start_lab_order(lab_id):
    authenticate("LabTechnician")
    lab = schema.get_lab_order(lab_id)
    if lab["status"] not in ("QUEUED", "REMAKE_QUEUED"):
        raise err("ERR_INVALID_STATE")

    from_queued = lab["status"] == "QUEUED"
    lab["status"] = "IN_PRODUCTION"
    store.touch(lab)

    # Bubble-up: only a first run (from QUEUED) drives the parent order.
    if from_queued:
        order = store.orders.get(lab["order_id"])
        if order is not None and order["fulfillment_status"] == "CONFIRMED":
            order["fulfillment_status"] = "IN_LAB"
            store.touch(order)

    return object_response(dump("lab_order", lab))


@bp.post("/lab-orders/<lab_id>/qc")
def qc_lab_order(lab_id):
    authenticate("LabTechnician")
    b = schema.body()
    result = schema.enum_field(b, "result", ("PASS", "FAIL"))
    failure_reason = schema.string_field(
        b, "failure_reason", required=(result == "FAIL"), default=None
    )

    lab = schema.get_lab_order(lab_id)
    if lab["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE")

    if result == "PASS":
        lab["status"] = "QC_PASSED"
        lab["qc_failure_reason"] = None
    else:
        # Priority 27 -- a failure is only accepted while remake_count < 2.
        if lab["remake_count"] >= REMAKE_LIMIT:
            raise err("ERR_REMAKE_LIMIT_EXCEEDED")
        lab["status"] = "REMAKE_QUEUED"
        lab["remake_count"] += 1
        lab["qc_failure_reason"] = failure_reason

    store.touch(lab)
    return object_response(dump("lab_order", lab))


@bp.post("/lab-orders/<lab_id>/ship")
def ship_lab_order(lab_id):
    authenticate("LabTechnician")
    lab = schema.get_lab_order(lab_id)
    if lab["status"] != "QC_PASSED":
        raise err("ERR_INVALID_STATE")

    order = store.orders.get(lab["order_id"])
    bopis = order is not None and order["delivery_method"] == "BOPIS"

    # Priority 12 -- a BOPIS lab order may only ship to an OPEN store.
    if bopis:
        shop = store.stores.get(order["store_id"])
        if shop is None or shop["status"] != "OPEN":
            raise err("ERR_STORE_CLOSED")

    lab["status"] = "SHIPPED"
    lab["shipped_to_store_id"] = order["store_id"] if bopis else None
    store.touch(lab)

    if order is not None and order["fulfillment_status"] == "IN_LAB":
        order["fulfillment_status"] = "READY_FOR_PICKUP" if bopis else "SHIPPED"
        if order["payment_status"] == "AUTHORIZED":
            order["payment_status"] = "CAPTURED"
        store.touch(order)

    return object_response(dump("lab_order", lab))


@bp.post("/lab-orders/<lab_id>/deliver")
def deliver_lab_order(lab_id):
    authenticate("StoreAssociate")
    lab = schema.get_lab_order(lab_id)
    if lab["status"] != "SHIPPED":
        raise err("ERR_INVALID_STATE")

    now = store.clock_now()
    lab["status"] = "DELIVERED"
    lab["delivered_at"] = store.iso_ms(now)
    lab["_delivered_at_dt"] = now
    store.touch(lab)

    order = store.orders.get(lab["order_id"])
    if order is not None and order["fulfillment_status"] in ("READY_FOR_PICKUP", "SHIPPED"):
        order["fulfillment_status"] = "DELIVERED"
        store.touch(order)

    return object_response(dump("lab_order", lab))
