"""Jobsite delivery: scheduling, handling and the delivery cascade
(PRD Section 3.8)."""
from flask import Blueprint

import clock
import constants as C
import db
import listing
import response
import serializers as ser
import validation as v
import calculations as calc
from errors import ApiError
from middleware import endpoint, require_owns_branch, require_owns_truck
from services import delivery as delivery_svc
from services import lookup

bp = Blueprint("delivery", __name__)


@bp.post("/delivery-runs")
@endpoint(["BranchOps"])
def create_delivery_run():
    body = v.body()
    sales_order_id = v.req_str(body, "sales_order_id")
    truck_id = v.req_str(body, "truck_id")
    window_start = v.req_datetime(body, "window_start")
    window_end = v.req_datetime(body, "window_end")
    jobsite_address = v.req_str(body, "jobsite_address")
    jobsite_has_forklift = v.opt_bool(body, "jobsite_has_forklift", False)

    # Body foreign keys resolve in declaration order: truck_id, then sales_order_id.
    truck = lookup.truck(truck_id)
    order = lookup.sales_order(sales_order_id)

    require_owns_branch(order["branch_id"])

    if truck["branch_id"] != order["branch_id"]:
        raise ApiError("ERR_TRUCK_BRANCH_MISMATCH")

    heaviest = delivery_svc.heaviest_pick_reel_lbs(order["id"])
    reel_handling = calc.jobsite_reel_handling(heaviest, jobsite_has_forklift)
    if reel_handling == "BOOM_LIFT" and not truck["has_boom_lift"]:
        raise ApiError("ERR_BOOM_LIFT_REQUIRED")

    if calc.truck_window_conflicts(lookup.runs_of_truck(truck_id), window_start, window_end):
        raise ApiError("ERR_TRUCK_WINDOW_CONFLICT")

    if any(r["status"] in ("SCHEDULED", "DISPATCHED") for r in lookup.runs_of_order(order["id"])):
        raise ApiError("ERR_ORDER_HAS_ACTIVE_RUN")

    rec = db.base_record()
    rec.update({
        "sales_order_id": sales_order_id,
        "truck_id": truck_id,
        "branch_id": order["branch_id"],
        "window_start": clock.iso(window_start),
        "window_end": clock.iso(window_end),
        "jobsite_address": jobsite_address,
        "jobsite_has_forklift": jobsite_has_forklift,
        "heaviest_reel_lbs": heaviest,
        "reel_handling": reel_handling,
        "status": "SCHEDULED",
        "dispatched_at": None,
        "delivered_at": None,
    })
    db.delivery_runs.add(rec)
    return response.object_response(ser.delivery_run(rec), 201)


@bp.get("/delivery-runs/<run_id>")
@endpoint(["PlatformAdmin", "BranchOps", "Driver", "Customer"])
def get_delivery_run(run_id):
    return response.object_response(ser.delivery_run(lookup.delivery_run(run_id)))


@bp.get("/delivery-runs")
@endpoint(["PlatformAdmin", "BranchOps", "Driver", "Customer"])
def list_delivery_runs():
    v.pagination()
    sales_order_id = v.query_str("sales_order_id")
    truck_id = v.query_str("truck_id")
    branch_id = v.query_str("branch_id")
    status = v.query_enum("status", C.RUN_STATUSES)

    rows = db.delivery_runs.values_ordered()
    if sales_order_id:
        rows = [r for r in rows if r["sales_order_id"] == sales_order_id]
    if truck_id:
        rows = [r for r in rows if r["truck_id"] == truck_id]
    if branch_id:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing.respond(rows, ser.delivery_run)


@bp.post("/delivery-runs/<run_id>/dispatch")
@endpoint(["Driver"])
def dispatch_delivery_run(run_id):
    v.body()
    run = lookup.delivery_run(run_id)
    require_owns_truck(run["truck_id"])

    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_INVALID_STATE")

    order = db.sales_orders.get(run["sales_order_id"])
    if order is None or order["fulfillment_status"] != "STAGED":
        raise ApiError("ERR_ORDER_NOT_STAGED")

    run["status"] = "DISPATCHED"
    run["dispatched_at"] = clock.iso_now()
    db.touch(run)
    return response.object_response(ser.delivery_run(run))


@bp.post("/delivery-runs/<run_id>/deliver")
@endpoint(["Driver"])
def deliver_delivery_run(run_id):
    v.body()
    run = lookup.delivery_run(run_id)
    require_owns_truck(run["truck_id"])

    if run["status"] != "DISPATCHED":
        raise ApiError("ERR_RUN_INVALID_STATE")

    run["status"] = "DELIVERED"
    run["delivered_at"] = clock.iso_now()
    db.touch(run)

    order = db.sales_orders.get(run["sales_order_id"])
    if order is not None and order["fulfillment_status"] == "STAGED":
        delivery_svc.deliver_cascade(order)
    return response.object_response(ser.delivery_run(run))
