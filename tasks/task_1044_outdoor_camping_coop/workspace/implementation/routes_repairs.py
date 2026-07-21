"""Repair order endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("repairs", __name__)


@bp.post("/coop/repair-orders")
def create_repair():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    product_id = c.require_str(body, "product_id")
    purchase_date = c.require_str(body, "purchase_date")
    c.require_owner_member(ctx, member_id)
    c.lookup("members", member_id)
    c.lookup("products", product_id)
    ro = {
        "member_id": member_id,
        "product_id": product_id,
        "rental_unit_id": None,
        "purchase_date": purchase_date,
        "repair_stage": "RECEIVED",
        "billing_stage": "UNBILLED",
        "warranty_status": "UNDETERMINED",
        "labor_cents": 0,
        "parts_cents": 0,
        "billed_cents": None,
    }
    store.stamp_new(ro)
    store.repair_orders[ro["id"]] = ro
    return c.ok(c.ser_repair(ro), 201)


@bp.get("/coop/repair-orders")
def list_repairs():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.repair_orders.values())
    if ctx.role == "Member":
        items = [r for r in items if r["member_id"] == ctx.user_id]
    for key in ("member_id", "product_id", "rental_unit_id", "repair_stage"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    return c.paginate_and_serialize(items, c.ser_repair)


@bp.get("/coop/repair-orders/<rid>")
def get_repair(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    r = c.lookup("repair_orders", rid)
    if ctx.role == "Member" and r["member_id"] != ctx.user_id:
        raise err("ERR_UNAUTHORIZED", "member may only access its own repair orders")
    return c.ok(c.ser_repair(r))


@bp.post("/coop/repair-orders/<rid>/diagnose")
def diagnose(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    body = c.get_body()
    labor = c.opt_int(body, "labor_cents", 0)
    parts = c.opt_int(body, "parts_cents", 0)
    r = c.lookup("repair_orders", rid)
    if r["repair_stage"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "repair order is not RECEIVED")
    r["labor_cents"] = labor
    r["parts_cents"] = parts
    covered = False
    if r["purchase_date"] is not None:
        pd = store._parse_instant(r["purchase_date"]).date()
        clock_date = store.clock.now().date()
        covered = (clock_date - pd).days <= c.WARRANTY_DAYS
    r["warranty_status"] = "COVERED" if covered else "DENIED"
    r["billed_cents"] = 0 if covered else (labor + parts)
    r["repair_stage"] = "DIAGNOSED"
    store.touch(r)
    return c.ok(c.ser_repair(r))


@bp.post("/coop/repair-orders/<rid>/start")
def start_repair(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    r = c.lookup("repair_orders", rid)
    if r["repair_stage"] != "DIAGNOSED":
        raise err("ERR_INVALID_STATE", "repair order is not DIAGNOSED")
    r["repair_stage"] = "IN_REPAIR"
    if r["billed_cents"] and r["billed_cents"] > 0:
        r["billing_stage"] = "INVOICED"
    store.touch(r)
    return c.ok(c.ser_repair(r))


@bp.post("/coop/repair-orders/<rid>/ready")
def ready_repair(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    r = c.lookup("repair_orders", rid)
    if r["repair_stage"] != "IN_REPAIR":
        raise err("ERR_INVALID_STATE", "repair order is not IN_REPAIR")
    r["repair_stage"] = "READY"
    store.touch(r)
    return c.ok(c.ser_repair(r))


@bp.post("/coop/repair-orders/<rid>/settle")
def settle_repair(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    r = c.lookup("repair_orders", rid)
    if r["billing_stage"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "repair order billing is not INVOICED")
    r["billing_stage"] = "SETTLED"
    store.touch(r)
    return c.ok(c.ser_repair(r))


@bp.post("/coop/repair-orders/<rid>/pickup")
def pickup_repair(rid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    r = c.lookup("repair_orders", rid)
    if r["repair_stage"] != "READY":
        raise err("ERR_INVALID_STATE", "repair order is not READY")
    billed = r["billed_cents"] or 0
    if not (r["billing_stage"] == "SETTLED" or billed == 0):
        raise err("ERR_REPAIR_UNSETTLED", "billable work is not settled")
    r["repair_stage"] = "PICKED_UP"
    store.touch(r)
    return c.ok(c.ser_repair(r))
