"""SpecialOrder endpoints."""
from flask import Blueprint

import db as _db
from db import db, new_entity, touch
from errors import (ApiError, duplicate, invalid_request, invalid_state,
                    not_found, unauthorized)
from helpers import (body, get_or_404, public, req_date, req_int, req_str)
from middleware import require, require_member_ownership
from response import success
from services import recompute_lot_status, recompute_on_hand

bp = Blueprint("special_orders", __name__)


@bp.post("/special-orders")
def create_special_order():
    role, uid = require(["Member", "ShopStaff"])
    data = body()
    member_id = data.get("member_id")
    if member_id is not None and isinstance(member_id, str):
        get_or_404(db["members"], member_id)
    member_id = req_str(data, "member_id")
    get_or_404(db["members"], member_id)
    if role == "Member" and uid != member_id:
        raise unauthorized("Member may only request own special order")
    requested_code = req_str(data, "requested_sku_code")
    quantity = req_int(data, "quantity", min_v=1)
    deposit = req_int(data, "deposit_cents", min_v=0)
    ent = new_entity({
        "member_id": member_id,
        "requested_sku_code": requested_code,
        "quantity": quantity,
        "resolved_sku_id": None,
        "deposit_cents": deposit,
        "status": "REQUESTED",
        "approved_by_user_id": None,
        "decline_reason": None,
    })
    db["special_orders"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/special-orders/<sid>")
def get_special_order(sid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    ent = get_or_404(db["special_orders"], sid)
    require_member_ownership(role, uid, ent["member_id"])
    return success(public(ent))


@bp.post("/special-orders/<sid>/approve")
def approve_special_order(sid):
    require(["ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    data = body()
    resolved = data.get("resolved_sku_id")
    if resolved is not None and isinstance(resolved, str):
        get_or_404(db["skus"], resolved)
    resolved = req_str(data, "resolved_sku_id")
    sku = get_or_404(db["skus"], resolved)
    approved_by = req_str(data, "approved_by_user_id")
    if so["status"] != "REQUESTED":
        raise invalid_state("Special order is not REQUESTED")
    if approved_by == so["member_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "approved_by_user_id must differ from member_id")
    if sku["discontinued"]:
        raise ApiError("ERR_SKU_DISCONTINUED", 422,
                       "Resolved SKU is discontinued")
    member = db["members"].get(so["member_id"])
    if member is None or member["wallet_credit_cents"] < so["deposit_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET", 422,
                       "Member wallet does not cover deposit")
    member["wallet_credit_cents"] -= so["deposit_cents"]
    touch(member)
    so["resolved_sku_id"] = resolved
    so["approved_by_user_id"] = approved_by
    so["status"] = "APPROVED"
    touch(so)
    return success(public(so))


@bp.post("/special-orders/<sid>/decline")
def decline_special_order(sid):
    require(["ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    data = body()
    reason = req_str(data, "decline_reason")
    if not reason.strip():
        raise invalid_request("decline_reason must be non-empty")
    if so["status"] != "REQUESTED":
        raise invalid_state("Special order is not REQUESTED")
    so["decline_reason"] = reason
    so["status"] = "DECLINED"
    touch(so)
    return success(public(so))


@bp.post("/special-orders/<sid>/mark-sourced")
def source_special_order(sid):
    require(["ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    if so["status"] != "APPROVED":
        raise invalid_state("Special order is not APPROVED")
    so["status"] = "SOURCED"
    touch(so)
    return success(public(so))


@bp.post("/special-orders/<sid>/receive")
def receive_special_order(sid):
    require(["ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    data = body()
    lot_code = req_str(data, "lot_code")
    qty_received = req_int(data, "qty_received", min_v=1)
    unit_cost_cents = req_int(data, "unit_cost_cents", min_v=0)
    expires_on = req_date(data, "expires_on")
    if so["status"] != "SOURCED":
        raise invalid_state("Special order is not SOURCED")
    sku_id = so["resolved_sku_id"]
    for lot in db["lots"].values():
        if lot["sku_id"] == sku_id and lot["lot_code"] == lot_code:
            raise duplicate("(sku_id, lot_code) already exists")
    ent = new_entity({
        "sku_id": sku_id,
        "lot_code": lot_code,
        "qty_received": qty_received,
        "qty_remaining": qty_received,
        "unit_cost_cents": unit_cost_cents,
        "expires_on": expires_on,
        "status": "ACTIVE",
        "quarantine_reason": None,
    })
    recompute_lot_status(ent)
    db["lots"][ent["id"]] = ent
    recompute_on_hand(sku_id)
    so["status"] = "RECEIVED"
    touch(so)
    return success(public(so))


@bp.post("/special-orders/<sid>/fulfill")
def fulfill_special_order(sid):
    require(["ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    if so["status"] != "RECEIVED":
        raise invalid_state("Special order is not RECEIVED")
    so["status"] = "FULFILLED"
    touch(so)
    member = db["members"].get(so["member_id"])
    if member is not None:
        member["loyalty_points_balance"] += 10 * so["quantity"]
        touch(member)
    return success(public(so))


@bp.post("/special-orders/<sid>/cancel")
def cancel_special_order(sid):
    role, uid = require(["Member", "ShopStaff"])
    so = get_or_404(db["special_orders"], sid)
    if role == "Member" and uid != so["member_id"]:
        raise unauthorized("Member may only cancel own special order")
    if so["status"] != "APPROVED":
        raise invalid_state("Special order is not APPROVED")
    so["status"] = "CANCELLED"  # deposit forfeited — no wallet change
    touch(so)
    return success(public(so))
