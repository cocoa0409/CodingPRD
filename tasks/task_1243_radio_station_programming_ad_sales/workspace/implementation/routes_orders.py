"""Routes: advertising orders and their sales workflow."""
from flask import Blueprint, request

import store
from helpers import (DAYPARTS, err, get_body, opt_str, paginate, req_date,
                     req_enum, req_int, req_present, req_str, require_role,
                     success_object)
from logic import (find, post_trade_reversal, ser_order, stamp_new, touch)

bp = Blueprint("orders", __name__)

ALL = ("ProgramDirector", "TrafficDirector", "SalesRep", "SalesManager",
       "BillingAdmin")


def _validate_daypart_targets(body):
    raw = req_present(body, "daypart_targets")
    if not isinstance(raw, list) or len(raw) == 0:
        err("ERR_BAD_REQUEST",
            "Field daypart_targets must be a non-empty array")
    seen = set()
    targets = []
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            err("ERR_BAD_REQUEST", f"daypart_targets[{i}] must be an object")
        daypart = req_enum(t, "daypart", set(DAYPARTS))
        units = req_int(t, "units", minimum=1)
        if daypart in seen:
            err("ERR_BAD_REQUEST",
                "daypart_targets dayparts must be unique")
        seen.add(daypart)
        targets.append({"daypart": daypart, "units": units})
    return targets


@bp.post("/orders")
def create_order():
    body = get_body()
    station_id = req_str(body, "station_id")
    advertiser_name = req_str(body, "advertiser_name")
    order_kind = req_enum(body, "order_kind", {"CASH", "TRADE"})
    trade_agreement_id = opt_str(body, "trade_agreement_id")
    flight_start = req_date(body, "flight_start")
    flight_end = req_date(body, "flight_end")
    rate_tier = req_enum(body, "rate_tier", {"FIXED", "PREEMPTIBLE"})
    reprice_policy = req_enum(body, "reprice_policy",
                              {"LOCKED_AT_BOOKING", "REPRICED_AT_AFFIDAVIT"})
    targets = _validate_daypart_targets(body)
    if flight_end < flight_start:
        err("ERR_BAD_REQUEST", "flight_end must be >= flight_start")
    user_id, _ = require_role("SalesRep")
    # Existence, left-to-right: station_id, then trade_agreement_id.
    find(store.stations, station_id)
    if trade_agreement_id is not None:
        find(store.trade_agreements, trade_agreement_id)
    # TRADE requires the reference; CASH forbids it.
    if order_kind == "TRADE" and trade_agreement_id is None:
        err("ERR_TRADE_AGREEMENT_REQUIRED",
            "TRADE order requires trade_agreement_id")
    if order_kind == "CASH" and trade_agreement_id is not None:
        err("ERR_TRADE_AGREEMENT_REQUIRED",
            "CASH order must not carry trade_agreement_id")
    rec = {"id": store.new_id(), "station_id": station_id,
           "advertiser_name": advertiser_name, "order_kind": order_kind,
           "trade_agreement_id": trade_agreement_id,
           "created_by_user_id": user_id,
           "flight_start": flight_start.isoformat(),
           "flight_end": flight_end.isoformat(), "rate_tier": rate_tier,
           "reprice_policy": reprice_policy, "daypart_targets": targets,
           "status": "DRAFT"}
    stamp_new(rec)
    store.orders[rec["id"]] = rec
    return success_object(ser_order(rec), 201)


@bp.get("/orders/<oid>")
def get_order(oid):
    require_role(*ALL)
    return success_object(ser_order(find(store.orders, oid)), 200)


@bp.get("/orders")
def list_orders():
    require_role(*ALL)
    recs = list(store.orders.values())
    station_id = request.args.get("station_id")
    agreement_id = request.args.get("trade_agreement_id")
    status = request.args.get("status")
    if station_id is not None:
        recs = [r for r in recs if r["station_id"] == station_id]
    if agreement_id is not None:
        recs = [r for r in recs if r["trade_agreement_id"] == agreement_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    return paginate(recs, ser_order)


def _trade_agreement_active_gate(order):
    if order["order_kind"] == "TRADE":
        agreement = store.trade_agreements.get(order["trade_agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            err("ERR_TRADE_AGREEMENT_INACTIVE",
                "Referenced TradeAgreement is not ACTIVE")


@bp.post("/orders/<oid>/submit")
def submit_order(oid):
    user_id, _ = require_role("SalesRep")
    order = find(store.orders, oid)
    if user_id != order["created_by_user_id"]:
        err("ERR_NOT_ORDER_OWNER",
            "Only the creating SalesRep may submit the order")
    if order["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Submit requires status DRAFT")
    _trade_agreement_active_gate(order)
    order["status"] = "SUBMITTED"
    touch(order)
    return success_object(ser_order(order), 200)


@bp.post("/orders/<oid>/approve")
def approve_order(oid):
    user_id, _ = require_role("SalesManager")
    order = find(store.orders, oid)
    if user_id == order["created_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "Approver must differ from the order creator")
    if order["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Approve requires status SUBMITTED")
    _trade_agreement_active_gate(order)
    order["status"] = "APPROVED"
    touch(order)
    return success_object(ser_order(order), 200)


@bp.post("/orders/<oid>/reject")
def reject_order(oid):
    require_role("SalesManager")
    order = find(store.orders, oid)
    if order["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "Reject requires status SUBMITTED")
    order["status"] = "REJECTED"
    touch(order)
    return success_object(ser_order(order), 200)


@bp.post("/orders/<oid>/activate")
def activate_order(oid):
    require_role("SalesManager")
    order = find(store.orders, oid)
    if order["status"] != "APPROVED":
        err("ERR_INVALID_STATE", "Activate requires status APPROVED")
    today = store.current_date().isoformat()
    if not (order["flight_start"] <= today <= order["flight_end"]):
        err("ERR_FLIGHT_WINDOW_INVALID",
            "Logical clock date must fall inside the flight window")
    order["status"] = "ACTIVE"
    touch(order)
    return success_object(ser_order(order), 200)


@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = require_role("SalesRep", "SalesManager")
    order = find(store.orders, oid)
    if role == "SalesRep" and user_id != order["created_by_user_id"]:
        err("ERR_NOT_ORDER_OWNER",
            "A SalesRep may cancel only their own orders")
    if order["status"] not in ("APPROVED", "ACTIVE"):
        err("ERR_INVALID_STATE",
            "Cancel requires status APPROVED or ACTIVE")
    # Cascade: SCHEDULED spots -> CANCELLED (TRADE spots post REVERSALs,
    # which may revive an EXHAUSTED agreement); MAKE_GOOD_PENDING spots ->
    # CANCELLED with the obligation voided (reason cleared; the TRADE
    # reversal already posted when the spot entered MAKE_GOOD_PENDING).
    for spot in sorted(
            (s for s in store.spots.values() if s["order_id"] == order["id"]),
            key=lambda s: s["_seq"]):
        if spot["status"] == "SCHEDULED":
            spot["status"] = "CANCELLED"
            touch(spot)
            post_trade_reversal(spot)
        elif spot["status"] == "MAKE_GOOD_PENDING":
            spot["status"] = "CANCELLED"
            spot["make_good_reason"] = None
            touch(spot)
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(ser_order(order), 200)


@bp.post("/orders/<oid>/complete")
def complete_order(oid):
    require_role("SalesManager")
    order = find(store.orders, oid)
    if order["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Complete requires status ACTIVE")
    today = store.current_date().isoformat()
    if not today > order["flight_end"]:
        err("ERR_FLIGHT_WINDOW_INVALID",
            "Logical clock date must be strictly past flight_end")
    for spot in store.spots.values():
        if (spot["order_id"] == order["id"]
                and spot["status"] in ("SCHEDULED", "MAKE_GOOD_PENDING")):
            err("ERR_INVALID_STATE",
                "Order still has open spot obligations")
    order["status"] = "COMPLETED"
    touch(order)
    return success_object(ser_order(order), 200)
