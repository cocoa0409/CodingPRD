"""Order lines (5 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import (LINE_STATUSES, MAX_ORDER_LINE_UNITS, MIN_ORDER_LINE_UNITS,
                            ROLES, SUBSTITUTION_PREFS)
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_body, enum_filter, free_filter,
                         gate_cycle_closed, gate_cycle_lock, gate_membership,
                         pagination, path_row, req_id, req_int, rung_cutoff,
                         rung_occ, rung_order_owner, opt_bool)
from core.store import DB, touch
from services import pricing, recompute

bp = Blueprint("lines", __name__)
R5 = list(ROLES)


def _context_of(order):
    drop_run = DB.get("DropRun", order["drop_run_id"])
    cycle = DB.get("Cycle", drop_run["cycle_id"]) if drop_run else None
    drop_point = DB.get("DropPoint", drop_run["drop_point_id"]) if drop_run else None
    route = DB.get("Route", drop_point["route_id"]) if drop_point else None
    return drop_run, cycle, route


def _rung28_cold_chain(item, route):
    if item["temp_class"] == "DRY":
        return
    if route is None or route["reefer_slots"] <= 0:
        raise ApiError("ERR_ROUTE_NO_COLD_CHAIN")


def _rung31_item_active(item):
    if item["status"] != "ACTIVE":
        raise ApiError("ERR_ITEM_DISCONTINUED")


def _rung32_price(item, cycle):
    if pricing.bound_price_version(item["id"], clock.parse(cycle["cutoff_at"])) is None:
        raise ApiError("ERR_NO_EFFECTIVE_PRICE")


def _rung33_quantity(item, qty_units):
    if qty_units < MIN_ORDER_LINE_UNITS or qty_units > MAX_ORDER_LINE_UNITS:
        raise ApiError("ERR_INVALID_QUANTITY")
    if not item["split_allowed"] and qty_units % item["case_pack_units"] != 0:
        raise ApiError("ERR_INVALID_QUANTITY")


@bp.post("/order-lines")
@endpoint(["ClubAdmin", "Member"])
def create_order_line(ctx):
    order = body_fk(ctx, "member_order_id")                # rung 5
    item = body_fk(ctx, "item_id")
    req_id(ctx, "member_order_id")                         # rung 7
    req_id(ctx, "item_id")
    qty_units = req_int(ctx, "qty_units")
    req_int(ctx, "expected_member_order_version")
    rollover_opt_in = opt_bool(ctx, "rollover_opt_in", default=False)
    substitution_pref = enum_body(ctx, "substitution_pref", SUBSTITUTION_PREFS,
                                  default="APPROVAL_REQUIRED")      # rung 8
    gate_cycle_closed(order)                               # rung 9
    gate_membership(DB.get("Member", order["member_id"]))  # rung 10
    drop_run, cycle, route = _context_of(order)
    gate_cycle_lock(cycle)                                 # rung 13
    rung_cutoff(cycle)                                     # rung 14
    rung_occ(ctx, "expected_member_order_version", order)  # rung 25
    rung_order_owner(ctx, order)                           # rung 26
    _rung28_cold_chain(item, route)                        # rung 28
    _rung31_item_active(item)                              # rung 31
    _rung32_price(item, cycle)                             # rung 32
    _rung33_quantity(item, qty_units)                      # rung 33
    for line in recompute.lines_of_order(order):           # rung 34
        if line["item_id"] == item["id"] and line["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_LINE_FOR_ITEM")
    row = DB.insert("OrderLine", {
        "member_order_id": order["id"], "item_id": item["id"], "qty_units": qty_units,
        "rollover_opt_in": rollover_opt_in, "substitution_pref": substitution_pref,
        "rolled_from_order_line_id": None, "status": "REQUESTED",
        "bound_case_price_cents": 0, "unit_price_cents": 0, "is_split_unit": False,
        "split_fee_per_unit_cents": 0, "confirmed_units": 0, "allocated_units": 0,
        "short_units": 0, "allocation_remainder_rank": 0, "line_gross_cents": 0,
    })
    touch(order)
    recompute.recompute_live_drop_subtotal(drop_run)
    return created(serialize.order_line(row))


@bp.get("/order-lines")
@endpoint(R5)
def list_order_lines(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", LINE_STATUSES)
    member_order_id = free_filter(ctx, "member_order_id")
    item_id = free_filter(ctx, "item_id")
    rolled_from = free_filter(ctx, "rolled_from_order_line_id")
    rows = []
    for row in DB.all("OrderLine"):
        if member_order_id is not None and row["member_order_id"] != member_order_id:
            continue
        if item_id is not None and row["item_id"] != item_id:
            continue
        if rolled_from is not None and row["rolled_from_order_line_id"] != rolled_from:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/order-lines/<order_line_id>")
@endpoint(R5)
def read_order_line(ctx, order_line_id):
    return ok(serialize.order_line(path_row("order_line_id", order_line_id)))


@bp.patch("/order-lines/<order_line_id>")
@endpoint(["ClubAdmin", "Member"])
def patch_order_line(ctx, order_line_id):
    line = path_row("order_line_id", order_line_id)        # rung 4
    order = DB.get("MemberOrder", line["member_order_id"])
    req_int(ctx, "expected_member_order_version")          # rung 7
    qty_units = None
    if "qty_units" in ctx.body and ctx.body["qty_units"] is not None:
        qty_units = req_int(ctx, "qty_units")
    rollover_opt_in = opt_bool(ctx, "rollover_opt_in", default=None)
    substitution_pref = enum_body(ctx, "substitution_pref", SUBSTITUTION_PREFS,
                                  default=None)            # rung 8
    gate_cycle_closed(order)                               # rung 9
    gate_membership(DB.get("Member", order["member_id"]))  # rung 10
    drop_run, cycle, route = _context_of(order)
    gate_cycle_lock(cycle)                                 # rung 13
    rung_cutoff(cycle)                                     # rung 14
    if line["status"] != "REQUESTED":                      # rung 17
        raise ApiError("ERR_INVALID_LINE_STATE")
    rung_occ(ctx, "expected_member_order_version", order)  # rung 25
    rung_order_owner(ctx, order)                           # rung 26
    item = DB.get("Item", line["item_id"])
    _rung28_cold_chain(item, route)                        # rung 28
    _rung31_item_active(item)                              # rung 31
    _rung32_price(item, cycle)                             # rung 32
    if qty_units is not None:
        _rung33_quantity(item, qty_units)                  # rung 33
        line["qty_units"] = qty_units
    if rollover_opt_in is not None:
        line["rollover_opt_in"] = rollover_opt_in
    if substitution_pref is not None:
        line["substitution_pref"] = substitution_pref
    touch(line)
    touch(order)
    recompute.recompute_live_drop_subtotal(drop_run)
    return ok(serialize.order_line(line))


@bp.post("/order-lines/<order_line_id>/cancel")
@endpoint(["ClubAdmin", "Member"])
def cancel_order_line(ctx, order_line_id):
    line = path_row("order_line_id", order_line_id)        # rung 4
    order = DB.get("MemberOrder", line["member_order_id"])
    req_int(ctx, "expected_member_order_version")          # rung 7
    gate_cycle_closed(order)                               # rung 9
    gate_membership(DB.get("Member", order["member_id"]))  # rung 10
    drop_run, cycle, _route = _context_of(order)
    gate_cycle_lock(cycle)                                 # rung 13
    rung_cutoff(cycle)                                     # rung 14
    if line["status"] != "REQUESTED":                      # rung 17
        raise ApiError("ERR_INVALID_LINE_STATE")
    rung_occ(ctx, "expected_member_order_version", order)  # rung 25
    rung_order_owner(ctx, order)                           # rung 26
    line["status"] = "CANCELLED"
    touch(line)
    touch(order)
    recompute.recompute_order_estimate(order)
    recompute.recompute_live_drop_subtotal(drop_run)
    return ok(serialize.order_line(line))
