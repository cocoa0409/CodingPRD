"""Branches and branch stock records."""

from flask import Blueprint, request

import domain
from db import store
from errors import err
from helpers import (get_body, new_id, opt_int, req_enum, req_int, req_str,
                     stamp_new, touch)
from middleware import require_any, require_roles
from response import ok, ok_list, paginate
from serialize import serialize, serialize_list

bp = Blueprint("branches", __name__)


def get_branch(bid):
    b = store.branches.get(bid)
    if b is None:
        raise err("ERR_BRANCH_NOT_FOUND", f"branch {bid} not found")
    return b


def get_stock(sid):
    s = store.stocks.get(sid)
    if s is None:
        raise err("ERR_BRANCH_STOCK_NOT_FOUND", f"branch stock {sid} not found")
    return s


# --------------------------------------------------------------- branches --

@bp.route("/motion/branches", methods=["POST"])
@require_roles("SystemAdmin")
def create_branch(user_id, role):
    body = get_body()
    code = req_str(body, "code")
    tz = req_int(body, "timezone_offset_hours")
    open_h = req_int(body, "business_open_hour")
    close_h = req_int(body, "business_close_hour")
    cutoff = req_int(body, "expedite_cutoff_hour")
    fee = req_int(body, "after_hours_fee_cents", minimum=0)
    for name, v in (("business_open_hour", open_h), ("business_close_hour", close_h),
                    ("expedite_cutoff_hour", cutoff)):
        if v < 0 or v > 23:
            raise err("ERR_INVALID_REQUEST", f"{name} must be in 0..23")
    if close_h <= open_h:
        raise err("ERR_INVALID_REQUEST", "business_close_hour must be > business_open_hour")
    if any(b["code"] == code for b in store.branches.values()):
        raise err("ERR_DUPLICATE_BRANCH_CODE", f"branch code {code} already exists")
    rec = stamp_new({
        "id": new_id(),
        "code": code,
        "timezone_offset_hours": tz,
        "business_open_hour": open_h,
        "business_close_hour": close_h,
        "expedite_cutoff_hour": cutoff,
        "after_hours_fee_cents": fee,
        "status": "OPEN",
    })
    store.branches[rec["id"]] = rec
    return ok(serialize("Branch", rec), 201)


@bp.route("/motion/branches", methods=["GET"])
@require_any
def list_branches(user_id, role):
    page, limit, offset, total = paginate(list(store.branches.values()))
    return ok_list(serialize_list("Branch", page), limit, offset, total)


@bp.route("/motion/branches/<bid>", methods=["GET"])
@require_any
def get_branch_route(user_id, role, bid):
    return ok(serialize("Branch", get_branch(bid)))


@bp.route("/motion/branches/<bid>", methods=["PATCH"])
@require_roles("SystemAdmin")
def patch_branch(user_id, role, bid):
    b = get_branch(bid)
    body = get_body()
    status = req_enum(body, "status", ("OPEN", "CLOSED"))
    b["status"] = status
    touch(b)
    return ok(serialize("Branch", b))


# ------------------------------------------------------------ branch stock --

@bp.route("/motion/branch-stocks", methods=["POST"])
@require_roles("BranchManager")
def create_stock(user_id, role):
    body = get_body()
    branch_id = req_str(body, "branch_id")
    product_id = req_str(body, "product_id")
    if branch_id not in store.branches:
        raise err("ERR_BRANCH_NOT_FOUND", f"branch {branch_id} not found")
    if product_id not in store.products:
        raise err("ERR_PRODUCT_NOT_FOUND", f"product {product_id} not found")
    on_hand = req_int(body, "on_hand_qty", minimum=0)
    lead = req_int(body, "factory_lead_time_days", minimum=0)
    reorder = opt_int(body, "reorder_point", default=0, minimum=0)
    rec = stamp_new({
        "id": new_id(),
        "branch_id": branch_id,
        "product_id": product_id,
        "on_hand_qty": on_hand,
        "factory_lead_time_days": lead,
        "reorder_point": reorder,
    })
    store.stocks[rec["id"]] = rec
    return ok(serialize("BranchStock", rec), 201)


@bp.route("/motion/branch-stocks", methods=["GET"])
@require_any
def list_stocks(user_id, role):
    items = list(store.stocks.values())
    q = request.args
    if q.get("branch_id") is not None:
        items = [s for s in items if s["branch_id"] == q["branch_id"]]
    if q.get("product_id") is not None:
        items = [s for s in items if s["product_id"] == q["product_id"]]
    page, limit, offset, total = paginate(items)
    return ok_list(serialize_list("BranchStock", page), limit, offset, total)


@bp.route("/motion/branch-stocks/<sid>", methods=["GET"])
@require_any
def get_stock_route(user_id, role, sid):
    return ok(serialize("BranchStock", get_stock(sid)))


@bp.route("/motion/branch-stocks/<sid>/adjust", methods=["POST"])
@require_roles("BranchManager")
def adjust_stock(user_id, role, sid):
    s = get_stock(sid)
    body = get_body()
    delta = req_int(body, "qty_delta")
    req_str(body, "reason")
    new_on_hand = s["on_hand_qty"] + delta
    if new_on_hand < domain.reserved_qty(s):
        raise err("ERR_STOCK_BELOW_RESERVED",
                  "adjustment would drop on_hand_qty below reserved_qty")
    s["on_hand_qty"] = new_on_hand
    touch(s)
    return ok(serialize("BranchStock", s))
