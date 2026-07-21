from flask import Blueprint, request

import store
import ledger
from calc import trade_in_value
from common import (
    authorize, get_json, need, as_enum,
    require_found, check_owner, parse_pagination, paginate,
)
from envelope import object_response, array_response
from errors import err

bp = Blueprint("tradeins", __name__)

GRADES = ("A", "B", "C", "D")
PAYOUT = ("CASH", "STORE_CREDIT")


@bp.post("/trade-ins")
def create_trade_in():
    _, role = authorize(["Member", "Clerk", "Manager"])
    body = get_json()
    mid = body.get("member_id")
    if mid is not None and mid not in store.members:
        raise err("ERR_NOT_FOUND", "member_id does not exist")
    pid = body.get("product_id")
    if pid is not None and pid not in store.products:
        raise err("ERR_NOT_FOUND", "product_id does not exist")
    member_id = need(body, "member_id")
    product_id = need(body, "product_id")
    stated_grade = as_enum(need(body, "stated_grade"), "stated_grade", GRADES)
    payout_method = as_enum(need(body, "payout_method"), "payout_method", PAYOUT)
    check_owner(role, request.headers.get("X-User-ID"), member_id)
    product = store.products[product_id]
    provisional = trade_in_value(product["base_trade_value_cents"], stated_grade, payout_method)
    t = store.make_record({
        "member_id": member_id,
        "product_id": product_id,
        "stated_grade": stated_grade,
        "final_grade": None,
        "payout_method": payout_method,
        "provisional_value_cents": provisional,
        "final_value_cents": None,
        "status": "SUBMITTED",
    })
    store.trade_ins[t["id"]] = t
    return object_response(store.serialize(t), 201)


@bp.get("/trade-ins/<tid>")
def get_trade_in(tid):
    authorize(["Member", "Clerk", "Manager"])
    t = require_found(store.trade_ins, tid)
    return object_response(store.serialize(t), 200)


@bp.get("/trade-ins")
def list_trade_ins():
    authorize(["Member", "Clerk", "Manager"])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    product_id = request.args.get("product_id")
    matching = list(store.trade_ins.values())
    if member_id is not None:
        matching = [t for t in matching if t["member_id"] == member_id]
    if product_id is not None:
        matching = [t for t in matching if t["product_id"] == product_id]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(t) for t in window], limit, offset, total)


@bp.post("/trade-ins/<tid>/grade")
def grade(tid):
    authorize(["Clerk", "Manager"])
    t = require_found(store.trade_ins, tid)
    body = get_json()
    final_grade = as_enum(need(body, "final_grade"), "final_grade", GRADES)
    if t["status"] not in ("SUBMITTED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Trade-in is not gradeable")
    product = store.products[t["product_id"]]
    t["final_grade"] = final_grade
    t["final_value_cents"] = trade_in_value(
        product["base_trade_value_cents"], final_grade, t["payout_method"])
    t["status"] = "OFFERED"
    store.touch(t)
    return object_response(store.serialize(t), 200)


@bp.post("/trade-ins/<tid>/dispute")
def dispute(tid):
    _, role = authorize(["Member", "Clerk", "Manager"])
    t = require_found(store.trade_ins, tid)
    check_owner(role, request.headers.get("X-User-ID"), t["member_id"])
    if t["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Only an OFFERED trade-in can be disputed")
    t["status"] = "DISPUTED"
    store.touch(t)
    return object_response(store.serialize(t), 200)


@bp.post("/trade-ins/<tid>/accept")
def accept(tid):
    _, role = authorize(["Member", "Clerk", "Manager"])
    t = require_found(store.trade_ins, tid)
    check_owner(role, request.headers.get("X-User-ID"), t["member_id"])
    if t["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Only an OFFERED trade-in can be accepted")
    t["status"] = "SETTLED"
    if t["payout_method"] == "STORE_CREDIT":
        ledger.add_entry(t["member_id"], t["final_value_cents"], "TRADE_IN_PAYOUT", t["id"])
        ledger.recompute_balance(store.members[t["member_id"]])
    store.touch(t)
    return object_response(store.serialize(t), 200)


@bp.post("/trade-ins/<tid>/void")
def void(tid):
    authorize(["Manager"])
    t = require_found(store.trade_ins, tid)
    if t["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Only a SETTLED trade-in can be voided")
    t["status"] = "VOIDED"
    had_payout = any(
        e["related_ref"] == t["id"] and e["reason"] == "TRADE_IN_PAYOUT"
        for e in store.store_credit_entries.values()
    )
    if had_payout:
        ledger.add_entry(t["member_id"], -t["final_value_cents"], "TRADE_IN_VOID_REVERSAL", t["id"])
        ledger.recompute_balance(store.members[t["member_id"]])
    store.touch(t)
    return object_response(store.serialize(t), 200)
