"""Orders and pre-trade compliance (PRD §3.4)."""
from flask import Blueprint, request

import audit
import db
import services as svc
from errors import raise_err
from middleware import (ALL_ROLES, body, paged, pagination, require_enum,
                        require_roles)
from response import ok_list, ok_object
from util import is_int, public

bp = Blueprint("orders", __name__)

ORDER_SIDES = ("BUY", "SELL")
ORDER_TYPES = ("MARKET", "LIMIT")


@bp.post("/trading/orders")
@require_roles("Trader")
def create_order():
    b = body()
    account_id = b.get("account_id")
    security_id = b.get("security_id")
    if not isinstance(account_id, str) or not account_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'account_id' is required")
    if not isinstance(security_id, str) or not security_id:
        raise_err("ERR_INVALID_REQUEST", "Field 'security_id' is required")
    side = require_enum(b, "side", ORDER_SIDES)
    qty = b.get("order_qty")
    if not is_int(qty) or qty <= 0:
        raise_err("ERR_INVALID_REQUEST", "Field 'order_qty' must be a positive integer")
    order_type = require_enum(b, "order_type", ORDER_TYPES)
    limit_price = b.get("limit_price_cents")
    if order_type == "LIMIT":
        if not is_int(limit_price) or limit_price <= 0:
            raise_err("ERR_INVALID_REQUEST",
                      "limit_price_cents is required and must be a positive integer for LIMIT orders")
    elif limit_price is not None:
        raise_err("ERR_INVALID_REQUEST", "limit_price_cents is forbidden for MARKET orders")
    account = svc.fetch("accounts", account_id, "ERR_ACCOUNT_NOT_FOUND")
    security = svc.fetch("securities", security_id, "ERR_SECURITY_NOT_FOUND")
    if account["status"] != "ACTIVE":
        raise_err("ERR_ACCOUNT_SUSPENDED", "Account is not ACTIVE")
    if account["account_type"] == "ERROR":
        raise_err("ERR_ACCOUNT_TYPE_FORBIDDEN", "ERROR accounts may not originate orders")
    if qty % security["lot_size"] != 0:
        raise_err("ERR_LOT_SIZE_VIOLATION", "order_qty must be a multiple of lot_size")
    rec = svc.new_record()
    rec.update({"account_id": account_id, "security_id": security_id, "side": side,
                "order_qty": qty, "order_type": order_type,
                "limit_price_cents": limit_price, "block_id": None,
                "status": "PENDING_COMPLIANCE", "allocated_qty": 0,
                "avg_executed_price_cents": None, "compliance_note": None})
    db.store["orders"][rec["id"]] = rec
    audit.record_request("Order", rec["id"], "ORDER_CREATED",
                         f"account_id: {account_id}; security_id: {security_id}; "
                         f"side: {side}; order_qty: {qty}; order_type: {order_type}")
    return ok_object(public(rec), 201)


@bp.get("/trading/orders/<orderId>")
@require_roles(*ALL_ROLES)
def get_order(orderId):
    return ok_object(public(svc.fetch("orders", orderId, "ERR_ORDER_NOT_FOUND")))


@bp.get("/trading/orders")
@require_roles(*ALL_ROLES)
def list_orders():
    limit, offset = pagination()
    items = sorted(db.store["orders"].values(), key=lambda r: r["_seq"])
    for param in ("account_id", "security_id", "block_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[param] == v]
    page, total = paged(items, limit, offset)
    return ok_list([public(o) for o in page], total, limit, offset)


def _applicable_restrictions(order):
    now = db.clock_now()
    out = []
    for r in db.store["restrictions"].values():
        if r["status"] != "ACTIVE":
            continue
        if r["account_id"] is not None and r["account_id"] != order["account_id"]:
            continue
        if r["security_id"] is not None and r["security_id"] != order["security_id"]:
            continue
        if r["side"] != "BOTH" and r["side"] != order["side"]:
            continue
        if not (r["_ef"] <= now <= r["_et"]):
            continue
        out.append(r)
    return out


@bp.post("/trading/orders/<orderId>/compliance-check")
@require_roles("ComplianceOfficer")
def compliance_check(orderId):
    order = svc.fetch("orders", orderId, "ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("PENDING_COMPLIANCE", "COMPLIANCE_REJECTED"):
        raise_err("ERR_INVALID_STATE",
                  f"Cannot run compliance-check on an order in {order['status']}")
    account = db.store["accounts"][order["account_id"]]
    security = db.store["securities"][order["security_id"]]
    if account["status"] != "ACTIVE":
        raise_err("ERR_ACCOUNT_SUSPENDED", "Account is not ACTIVE")
    if security["status"] != "ACTIVE":
        raise_err("ERR_SECURITY_HALTED", "Security is not ACTIVE")
    # restriction rules: PROHIBITED precedence over MAX_POSITION_UNITS
    note = None
    rules = _applicable_restrictions(order)
    if any(r["rule_type"] == "PROHIBITED" for r in rules):
        note = "ERR_TRADE_PROHIBITED"
    else:
        signed = order["order_qty"] if order["side"] == "BUY" else -order["order_qty"]
        projected = svc.position_net_qty(order["account_id"], order["security_id"]) + signed
        for r in rules:
            if r["rule_type"] == "MAX_POSITION_UNITS" and projected > r["threshold_units"]:
                note = "ERR_POSITION_LIMIT_BREACH"
                break
    frm = order["status"]
    if note is not None:
        order["status"] = "COMPLIANCE_REJECTED"
        order["compliance_note"] = note
        svc.touch(order)
        audit.record_request("Order", order["id"], "ORDER_COMPLIANCE_REJECTED",
                             f"status: {frm} -> COMPLIANCE_REJECTED; compliance_note: {note}")
    else:
        order["status"] = "APPROVED"
        order["compliance_note"] = None
        svc.touch(order)
        audit.record_request("Order", order["id"], "ORDER_COMPLIANCE_APPROVED",
                             f"status: {frm} -> APPROVED")
    return ok_object(public(order))


@bp.post("/trading/orders/<orderId>/cancel")
@require_roles("Trader")
def cancel_order(orderId):
    order = svc.fetch("orders", orderId, "ERR_ORDER_NOT_FOUND")
    if order["status"] not in ("PENDING_COMPLIANCE", "COMPLIANCE_REJECTED", "APPROVED"):
        raise_err("ERR_INVALID_STATE", f"Cannot cancel an order in {order['status']}")
    frm = order["status"]
    order["status"] = "CANCELLED"
    svc.touch(order)
    audit.record_request("Order", order["id"], "ORDER_CANCELLED",
                         f"status: {frm} -> CANCELLED")
    return ok_object(public(order))
