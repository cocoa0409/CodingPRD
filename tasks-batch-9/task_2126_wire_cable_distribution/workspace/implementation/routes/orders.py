"""Sales orders, order lines, the allocation run, the release compensation and
the reel return (PRD Sections 3.5, 3.6 and 3.9)."""
from flask import Blueprint, g

import constants as C
import db
import listing
import response
import serializers as ser
import validation as v
import calculations as calc
from errors import ApiError
from middleware import endpoint, require_owns_branch, require_owns_customer
from services import allocation as allocation_svc
from services import delivery as delivery_svc
from services import lookup

bp = Blueprint("orders", __name__)


@bp.get("/sales-orders/<order_id>")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "CreditManager", "Customer"])
def get_sales_order(order_id):
    order = lookup.sales_order(order_id)
    require_owns_branch(order["branch_id"])
    require_owns_customer(order["customer_id"])
    return response.object_response(ser.sales_order(order))


@bp.get("/sales-orders")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "CreditManager", "Customer"])
def list_sales_orders():
    v.pagination()
    customer_id = v.query_str("customer_id")
    quote_id = v.query_str("quote_id")
    branch_id = v.query_str("branch_id")
    fulfillment_status = v.query_enum("fulfillment_status", C.FULFILLMENT_STATUSES)
    billing_status = v.query_enum("billing_status", C.BILLING_STATUSES)

    rows = db.sales_orders.values_ordered()
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if quote_id:
        rows = [r for r in rows if r["quote_id"] == quote_id]
    if branch_id:
        rows = [r for r in rows if r["branch_id"] == branch_id]
    if fulfillment_status:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment_status]
    if billing_status:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    return listing.respond(rows, ser.sales_order)


@bp.get("/order-lines/<order_line_id>")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "Customer"])
def get_order_line(order_line_id):
    return response.object_response(ser.order_line(lookup.order_line(order_line_id)))


@bp.get("/order-lines")
@endpoint(["PlatformAdmin", "SalesRep", "BranchOps", "Customer"])
def list_order_lines():
    v.pagination()
    sales_order_id = v.query_str("sales_order_id")
    product_id = v.query_str("product_id")
    allocation_status = v.query_enum("allocation_status", C.LINE_ALLOCATION_STATUSES)

    rows = db.order_lines.values_ordered()
    if sales_order_id:
        rows = [r for r in rows if r["sales_order_id"] == sales_order_id]
    if product_id:
        rows = [r for r in rows if r["product_id"] == product_id]
    if allocation_status:
        rows = [r for r in rows if r["allocation_status"] == allocation_status]
    if sales_order_id:
        rows = sorted(rows, key=lambda r: r["line_number"])
    return listing.respond(rows, ser.order_line)


@bp.post("/sales-orders/<order_id>/allocate")
@endpoint(["BranchOps"])
def allocate_order(order_id):
    body = v.body()
    policy = v.opt_enum(body, "allocation_policy", C.ALLOCATION_POLICIES, "MINIMIZE_REMNANT")
    expected_version = v.req_int(body, "expected_sales_order_version")

    order = lookup.sales_order(order_id)
    require_owns_branch(order["branch_id"])

    if order["fulfillment_status"] not in ("PENDING_ALLOCATION", "PARTIALLY_ALLOCATED"):
        raise ApiError("ERR_ORDER_NOT_ALLOCATABLE")

    # Ladder 14 then 20: the plan is produced without persisting anything.
    plans, lot_pins = allocation_svc.plan_allocation(order, policy)
    if not plans:
        raise ApiError("ERR_NO_ELIGIBLE_REEL")

    customer = db.customers.get(order["customer_id"])
    if customer is not None and customer["credit_status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD")

    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")

    allocation_svc.apply_allocation(order, plans, lot_pins)

    lines = lookup.order_lines_of(order["id"])
    if lines and all(line["allocation_status"] == "FULLY_ALLOCATED" for line in lines):
        order["fulfillment_status"] = "ALLOCATED"
    else:
        order["fulfillment_status"] = "PARTIALLY_ALLOCATED"
    order["allocation_policy"] = policy
    db.touch(order)
    return response.object_response(ser.sales_order(order))


@bp.post("/sales-orders/<order_id>/release-allocations")
@endpoint(["BranchOps"])
def release_allocations(order_id):
    v.body()
    order = lookup.sales_order(order_id)
    require_owns_branch(order["branch_id"])

    if order["fulfillment_status"] not in ("PARTIALLY_ALLOCATED", "ALLOCATED"):
        raise ApiError("ERR_ORDER_NOT_ALLOCATABLE")

    allocs = lookup.allocations_of_order(order["id"])
    if any(a["status"] in ("COMMITTED", "CONSUMED") for a in allocs):
        raise ApiError("ERR_ALLOCATION_NOT_RESERVED")

    allocation_svc.release_allocations_of_order(order)

    for line in lookup.order_lines_of(order["id"]):
        line["allocated_length_ft"] = 0
        line["allocation_status"] = "UNALLOCATED"
        db.touch(line)

    order["fulfillment_status"] = "PENDING_ALLOCATION"
    db.touch(order)
    return response.object_response(ser.sales_order(order))


@bp.post("/order-lines/<order_line_id>/return")
@endpoint(["BranchOps"])
def return_reel(order_line_id):
    body = v.body()
    reel_id = v.req_str(body, "reel_id")
    condition = v.req_enum(body, "condition", C.RETURN_CONDITIONS)

    order_line = lookup.order_line(order_line_id)
    reel = lookup.reel(reel_id)

    require_owns_branch(reel["branch_id"])

    order = db.sales_orders.get(order_line["sales_order_id"])
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_ORDER_NOT_DELIVERED")

    if not order_line["returnable"]:
        raise ApiError("ERR_CUT_ITEM_NON_RETURNABLE")

    if reel["delivered_sales_order_id"] != order_line["sales_order_id"]:
        raise ApiError("ERR_REEL_NOT_ON_ORDER_LINE")

    if reel["status"] != "ON_JOBSITE":
        raise ApiError("ERR_REEL_NOT_ON_JOBSITE")

    product = db.products[reel["product_id"]]
    delivery_svc.return_cascade(order_line, order, reel, product, condition)
    return response.object_response(ser.reel(reel))
