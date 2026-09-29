"""Bench reservations."""

from flask import Blueprint

import bench_ops
import calc
import store
import validate as v
import views
from auth import (ALL_ROLES, RESERVATION_ACTIONS, authenticate,
                  require_action_role, require_roles)
from errors import fail
from response import created, listing, ok
from routes_orders import path_order

bp = Blueprint("bench", __name__)

RESERVATION_ADVANCE = {"CONFIRM", "RELEASE"}


@bp.post("/shop/bench-reservations")
def create_reservation():
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    body = v.body()
    order_id = v.req_fk(body, "rebuild_order_id")
    bench_id = v.req_fk(body, "bench_id")
    start = v.req_ts(body, "window_start_at")
    end = v.req_ts(body, "window_end_at")
    queue_if_full = v.opt_bool(body, "queue_if_full", False)
    if end <= start:
        fail("ERR_INVALID_REQUEST", "window_end_at must be strictly after window_start_at")

    order = store.get("orders", order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "Rebuild order %s not found" % order_id)
    bench = store.get("benches", bench_id)
    if bench is None:
        fail("ERR_BENCH_NOT_FOUND", "Bench %s not found" % bench_id)

    standard = calc.standard_for_order(order)
    if standard is not None and standard.get("cleanroom_required") and not bench.get("cleanroom"):
        fail("ERR_CLEANROOM_BENCH_REQUIRED", "this model requires a cleanroom bench")

    if calc.admits(bench, start, end):
        status = "HELD"
    elif queue_if_full:
        status = "QUEUED"
    else:
        fail("ERR_BENCH_WINDOW_CONFLICT", "the bench is at capacity for that window")

    rec = store.base_record()
    rec.update({
        "rebuild_order_id": order_id,
        "bench_id": bench_id,
        "window_start_at": body["window_start_at"],
        "window_end_at": body["window_end_at"],
        "queue_if_full": queue_if_full,
        "status": status,
        "window_minutes": calc.window_minutes(start, end),
        "promoted_at": None,
    })
    store.insert("reservations", rec)
    calc.recompute_committed_minutes(bench)
    return created(views.render("reservations", rec))


@bp.get("/shop/rebuild-orders/<oid>/bench-reservations")
def list_order_reservations(oid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    order = path_order(oid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "orders", order)
    rows = calc.reservations_of_order(order["id"])
    status = v.qparam("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("reservations", page), limit, offset, total)


@bp.post("/shop/bench-reservations/<rid>/advance")
def advance_reservation(rid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    raw = v.body()
    require_action_role(role, raw.get("action"), RESERVATION_ACTIONS)
    res = store.get("reservations", rid)
    if res is None:
        fail("ERR_RESERVATION_NOT_FOUND", "Bench reservation %s not found" % rid)
    action = v.req_enum(raw, "action", RESERVATION_ADVANCE)

    bench = store.get("benches", res["bench_id"])
    if action == "CONFIRM":
        if res["status"] != "HELD":
            fail("ERR_RESERVATION_INVALID_STATE", "reservation is not HELD")
        res["status"] = "CONFIRMED"
        store.touch(res)
        calc.recompute_committed_minutes(bench)
    else:
        if res["status"] not in ("QUEUED", "HELD", "CONFIRMED"):
            fail("ERR_RESERVATION_INVALID_STATE", "reservation may not be released")
        if res["status"] == "CONFIRMED":
            order = store.get("orders", res["rebuild_order_id"])
            if order is not None and order["work_status"] == "IN_PROGRESS":
                fail("ERR_RESERVATION_INVALID_STATE",
                     "a confirmed window may not be released while the order is in progress")
        res["status"] = "RELEASED"
        store.touch(res)
        bench_ops.free_capacity(bench)
    return ok(views.render("reservations", res))
