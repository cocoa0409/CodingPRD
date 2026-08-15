"""Allocation order resources (PRD 3.8)."""

from flask import request

from calc import CHANNELS
from db import STORES, new_record, touch
from errors import ApiError, invalid_state
from helpers import auth, body, f_enum, f_int, f_str, filter_and_page, get_or_404
from response import serialize, success
from routes import make_bp

bp = make_bp("allocation_orders")

GET_ROLES = ("PlantAdmin", "SalesPlanner", "CutWrapOperator", "QAGrader")


@bp.post("/plant/allocation-orders")
def create_order():
    auth("SalesPlanner")
    b = body()
    cheese_batch_id = f_str(b, "cheese_batch_id")
    channel = f_enum(b, "channel", CHANNELS)
    customer_name = f_str(b, "customer_name")
    wheels_requested = f_int(b, "wheels_requested", positive=True)
    priority = f_int(b, "priority")
    batch = get_or_404("cheese_batches", cheese_batch_id, "cheese batch")
    # Rung 8: the batch must be RELEASED before allocation.
    if batch["status"] != "RELEASED":
        raise ApiError(
            "ERR_BATCH_NOT_RELEASED", 409, "Batch status is not RELEASED"
        )
    rec = new_record()
    rec.update(
        plant_id=batch["plant_id"],
        cheese_batch_id=batch["id"],
        channel=channel,
        customer_name=customer_name,
        wheels_requested=wheels_requested,
        wheels_cut=0,
        priority=priority,
        status="OPEN",
    )
    STORES["allocation_orders"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/plant/allocation-orders/<allocationOrderId>")
def get_order(allocationOrderId):
    auth(*GET_ROLES)
    rec = get_or_404("allocation_orders", allocationOrderId, "allocation order")
    return success(serialize(rec))


@bp.get("/plant/allocation-orders")
def list_orders():
    auth(*GET_ROLES)
    data, pagination = filter_and_page(
        "allocation_orders",
        [
            ("plant_id", request.args.get("plant_id")),
            ("cheese_batch_id", request.args.get("cheese_batch_id")),
            ("channel", request.args.get("channel")),
            ("status", request.args.get("status")),
        ],
        serialize,
    )
    return success(data, 200, pagination)


@bp.post("/plant/allocation-orders/<allocationOrderId>/cancel")
def cancel_order(allocationOrderId):
    auth("SalesPlanner")
    body(required=False)
    rec = get_or_404("allocation_orders", allocationOrderId, "allocation order")
    if rec["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        invalid_state("Only an OPEN or PARTIALLY_FILLED order may be cancelled")
    if rec["wheels_cut"] > 0:
        raise ApiError(
            "ERR_ORDER_HAS_CUTS", 409, "Cancel attempted on an order with wheels_cut > 0"
        )
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(serialize(rec))
