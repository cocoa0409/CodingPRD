"""The commit fork: cutting footage and picking whole reels (PRD Section 3.7)."""
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
from middleware import endpoint, require_owns_branch
from services import allocation as allocation_svc
from services import lookup

bp = Blueprint("allocations", __name__)


@bp.get("/allocations/<allocation_id>")
@endpoint(["PlatformAdmin", "BranchOps", "SalesRep"])
def get_allocation(allocation_id):
    return response.object_response(ser.allocation(lookup.allocation(allocation_id)))


@bp.get("/allocations")
@endpoint(["PlatformAdmin", "BranchOps", "SalesRep"])
def list_allocations():
    v.pagination()
    order_line_id = v.query_str("order_line_id")
    sales_order_id = v.query_str("sales_order_id")
    reel_id = v.query_str("reel_id")
    remnant_reel_id = v.query_str("remnant_reel_id")
    status = v.query_enum("status", C.ALLOCATION_STATUSES)

    rows = db.allocations.values_ordered()
    if order_line_id:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if sales_order_id:
        rows = [r for r in rows if r["sales_order_id"] == sales_order_id]
    if reel_id:
        rows = [r for r in rows if r["reel_id"] == reel_id]
    if remnant_reel_id:
        rows = [r for r in rows if r["remnant_reel_id"] == remnant_reel_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if order_line_id:
        rows = sorted(rows, key=lambda r: r["sequence_no"])
    return listing.respond(rows, ser.allocation)


@bp.post("/allocations/<allocation_id>/cut")
@endpoint(["BranchOps"])
def cut_allocation(allocation_id):
    body = v.body()
    window_start = v.req_datetime(body, "cut_window_start")
    window_end = v.req_datetime(body, "cut_window_end")

    alloc = lookup.allocation(allocation_id)
    reel = db.reels[alloc["reel_id"]]
    require_owns_branch(reel["branch_id"])

    if alloc["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_NOT_RESERVED")

    order_line = db.order_lines[alloc["order_line_id"]]
    if order_line["put_up"] != "CUT":
        raise ApiError("ERR_PUT_UP_MISMATCH")

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_CUT_WINDOW")

    branch = db.branches[reel["branch_id"]]
    occupied = [
        a for a in db.allocations.values()
        if a["status"] in ("COMMITTED", "CONSUMED")
        and a["commit_mode"] == "CUT"
        and a["cut_window_start"] is not None
        and db.reels.get(a["reel_id"]) is not None
        and db.reels[a["reel_id"]]["branch_id"] == reel["branch_id"]
    ]
    overlaps = calc.cut_floor_overlap_count(occupied, window_start, window_end)
    if overlaps >= branch["concurrent_cut_capacity"]:
        raise ApiError("ERR_CUT_BAY_CAPACITY_EXCEEDED")

    product = db.products[reel["product_id"]]

    alloc["status"] = "COMMITTED"
    alloc["commit_mode"] = "CUT"
    alloc["cut_window_start"] = clock.iso(window_start)
    alloc["cut_window_end"] = clock.iso(window_end)
    alloc["cut_charge_applied_cents"] = calc.cut_charge_tier(
        order_line["billable_length_ft"], product["cut_charge_cents"]
    )

    reel["current_length_ft"] = calc.as_number(
        calc.dec(reel["current_length_ft"]) - calc.dec(alloc["length_ft"])
    )
    reel["allocated_length_ft"] = calc.as_number(
        calc.dec(reel["allocated_length_ft"]) - calc.dec(alloc["length_ft"])
    )
    allocation_svc.settle_reel_after_cut(reel, alloc, product, branch)
    db.touch(alloc)

    order = db.sales_orders[alloc["sales_order_id"]]
    allocation_svc.bubble_order_to_staged(order)
    return response.object_response(ser.allocation(alloc))


@bp.post("/allocations/<allocation_id>/pick")
@endpoint(["BranchOps"])
def pick_allocation(allocation_id):
    v.body()
    alloc = lookup.allocation(allocation_id)
    reel = db.reels[alloc["reel_id"]]
    require_owns_branch(reel["branch_id"])

    if alloc["status"] != "RESERVED":
        raise ApiError("ERR_ALLOCATION_NOT_RESERVED")

    order_line = db.order_lines[alloc["order_line_id"]]
    if order_line["put_up"] != "MASTER_REEL":
        raise ApiError("ERR_PUT_UP_MISMATCH")

    alloc["status"] = "COMMITTED"
    alloc["commit_mode"] = "PICK"
    db.touch(alloc)

    order = db.sales_orders[alloc["sales_order_id"]]
    allocation_svc.bubble_order_to_staged(order)
    return response.object_response(ser.allocation(alloc))
