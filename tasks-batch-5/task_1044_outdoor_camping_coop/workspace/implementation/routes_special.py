"""Special order endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("special", __name__)


@bp.post("/coop/special-orders")
def create_special():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    product_id = c.require_str(body, "product_id")
    quantity = c.require_int(body, "quantity")
    c.require_owner_member(ctx, member_id)
    c.lookup("members", member_id)
    c.lookup("products", product_id)
    if quantity <= 0:
        raise err("ERR_INVALID_QUANTITY", "quantity must be > 0")
    so = {
        "member_id": member_id,
        "product_id": product_id,
        "quantity": quantity,
        "status": "REQUESTED",
        "quoted_price_cents": None,
        "deposit_cents": None,
    }
    store.stamp_new(so)
    store.special_orders[so["id"]] = so
    return c.ok(c.ser_special_order(so), 201)


@bp.get("/coop/special-orders")
def list_special():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.special_orders.values())
    if ctx.role == "Member":
        items = [s for s in items if s["member_id"] == ctx.user_id]
    for key in ("member_id", "product_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    return c.paginate_and_serialize(items, c.ser_special_order)


@bp.get("/coop/special-orders/<sid>")
def get_special(sid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    s = c.lookup("special_orders", sid)
    c.require_owner_member(ctx, s["member_id"])
    return c.ok(c.ser_special_order(s))


@bp.post("/coop/special-orders/<sid>/quotes")
def quote(sid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    body = c.get_body()
    quoted_price = c.require_int(body, "quoted_price_cents")
    expected_version = c.require_int(body, "expected_special_order_version")
    s = c.lookup("special_orders", sid)
    if s["status"] not in ("REQUESTED", "QUOTED"):
        raise err("ERR_INVALID_STATE", "special order cannot be quoted from its current state")
    if expected_version != s["version"]:
        raise err("ERR_STALE_VERSION", "expected_special_order_version does not match")
    s["quoted_price_cents"] = quoted_price
    s["status"] = "QUOTED"
    store.touch(s)
    return c.ok(c.ser_special_order(s))


@bp.post("/coop/special-orders/<sid>/confirm")
def confirm(sid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member"})
    s = c.lookup("special_orders", sid)
    c.require_owner_member(ctx, s["member_id"])
    if s["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "special order is not QUOTED")
    deposit = c.floor_mul(s["quoted_price_cents"], c.SPECIAL_ORDER_DEPOSIT_PCT)
    member = store.members[s["member_id"]]
    if member["wallet_credit_cents"] < deposit:
        raise err("ERR_INSUFFICIENT_WALLET", "wallet cannot cover the required deposit")
    member["wallet_credit_cents"] -= deposit
    store.touch(member)
    s["deposit_cents"] = deposit
    s["status"] = "CONFIRMED"
    store.touch(s)
    return c.ok(c.ser_special_order(s))


@bp.post("/coop/special-orders/<sid>/fulfill")
def fulfill(sid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    s = c.lookup("special_orders", sid)
    if s["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "special order is not CONFIRMED")
    s["status"] = "FULFILLED"
    store.touch(s)
    return c.ok(c.ser_special_order(s))


@bp.post("/coop/special-orders/<sid>/cancel")
def cancel_special(sid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    s = c.lookup("special_orders", sid)
    c.require_owner_member(ctx, s["member_id"])
    if s["status"] not in ("REQUESTED", "QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "special order cannot be cancelled from its current state")
    s["status"] = "CANCELLED"
    store.touch(s)
    if s["deposit_cents"] and s["deposit_cents"] > 0:
        member = store.members.get(s["member_id"])
        if member is not None:
            member["wallet_credit_cents"] += s["deposit_cents"]
            store.touch(member)
    return c.ok(c.ser_special_order(s))
