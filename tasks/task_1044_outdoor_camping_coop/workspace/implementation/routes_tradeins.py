"""Trade-in endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("tradeins", __name__)


@bp.post("/coop/trade-ins")
def create_tradein():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    product_id = c.require_str(body, "product_id")
    grade = c.require_enum(body, "condition_grade", {"A", "B", "C"})
    c.require_owner_member(ctx, member_id)
    c.lookup("members", member_id)
    c.lookup("products", product_id)
    ti = {
        "member_id": member_id,
        "product_id": product_id,
        "condition_grade": grade,
        "status": "SUBMITTED",
        "offered_cash_cents": None,
        "offered_credit_cents": None,
        "counter_ask_cents": None,
        "rounds": 0,
        "accepted_payout_type": None,
        "accepted_payout_cents": None,
    }
    store.stamp_new(ti)
    store.trade_ins[ti["id"]] = ti
    return c.ok(c.ser_trade_in(ti), 201)


@bp.get("/coop/trade-ins")
def list_tradeins():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.trade_ins.values())
    if ctx.role == "Member":
        items = [t for t in items if t["member_id"] == ctx.user_id]
    for key in ("member_id", "product_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t[key] == val]
    return c.paginate_and_serialize(items, c.ser_trade_in)


@bp.get("/coop/trade-ins/<tid>")
def get_tradein(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    t = c.lookup("trade_ins", tid)
    c.require_owner_member(ctx, t["member_id"])
    return c.ok(c.ser_trade_in(t))


@bp.post("/coop/trade-ins/<tid>/offer")
def offer(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    t = c.lookup("trade_ins", tid)
    if t["status"] not in ("SUBMITTED", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "trade-in cannot be offered from its current state")
    product = store.products[t["product_id"]]
    base = product["retail_price_cents"]
    gf = c.GRADE_FACTOR[t["condition_grade"]]
    t["offered_cash_cents"] = c.floor_prod(base, gf, c.CASH_FACTOR)
    t["offered_credit_cents"] = c.floor_prod(base, gf, c.CREDIT_FACTOR)
    t["status"] = "OFFERED"
    store.touch(t)
    return c.ok(c.ser_trade_in(t))


@bp.post("/coop/trade-ins/<tid>/counter")
def counter(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member"})
    body = c.get_body()
    counter_ask = c.require_int(body, "counter_ask_cents")
    t = c.lookup("trade_ins", tid)
    c.require_owner_member(ctx, t["member_id"])
    if t["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "trade-in is not OFFERED")
    if t["rounds"] >= c.MAX_TRADE_IN_ROUNDS:
        raise err("ERR_TRADE_IN_ROUNDS_EXCEEDED", "maximum negotiation rounds reached")
    t["rounds"] += 1
    t["counter_ask_cents"] = counter_ask
    t["status"] = "COUNTERED"
    store.touch(t)
    return c.ok(c.ser_trade_in(t))


@bp.post("/coop/trade-ins/<tid>/accept")
def accept(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member"})
    body = c.get_body()
    payout_type = c.require_enum(body, "accepted_payout_type", {"CASH", "CREDIT"})
    t = c.lookup("trade_ins", tid)
    c.require_owner_member(ctx, t["member_id"])
    if t["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "trade-in is not OFFERED")
    amount = t["offered_cash_cents"] if payout_type == "CASH" else t["offered_credit_cents"]
    t["accepted_payout_type"] = payout_type
    t["accepted_payout_cents"] = amount
    t["status"] = "ACCEPTED"
    store.touch(t)
    if payout_type == "CREDIT":
        member = store.members.get(t["member_id"])
        if member is not None:
            member["wallet_credit_cents"] += amount
            store.touch(member)
    return c.ok(c.ser_trade_in(t))


@bp.post("/coop/trade-ins/<tid>/reject")
def reject(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member"})
    t = c.lookup("trade_ins", tid)
    c.require_owner_member(ctx, t["member_id"])
    if t["status"] not in ("OFFERED", "COUNTERED"):
        raise err("ERR_INVALID_STATE", "trade-in cannot be rejected from its current state")
    t["status"] = "REJECTED"
    store.touch(t)
    return c.ok(c.ser_trade_in(t))
