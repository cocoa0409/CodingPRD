"""Special orders and design consultations."""
from datetime import timedelta

from flask import Blueprint

import serializers
from auth import require, check_designer_ownership
from envelope import ok, created
from errors import err
from listing import list_response
from store import db, new_base, insert, touch, fetch, fk
from validation import get_body, req_str, req_int, opt_int
from timeutil import floor_days

bp = Blueprint("workflow", __name__)

GET_ALL = ("ShowroomAssociate", "StoreManager", "Designer", "FulfillmentCoordinator")


# --------------------------- SpecialOrder ---------------------------
@bp.post("/special-orders")
@require("ShowroomAssociate", "StoreManager")
def create_special_order():
    body = get_body()
    order_id = body.get("order_id")
    if order_id is None:
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    fk("orders", order_id)
    order_line_id = body.get("order_line_id")
    if order_line_id is None:
        raise err("ERR_INVALID_REQUEST", "order_line_id is required")
    fk("order_lines", order_line_id)
    supplier_lead_days = req_int(body, "supplier_lead_days")
    rec = new_base()
    rec.update(
        {
            "order_id": order_id,
            "order_line_id": order_line_id,
            "supplier_lead_days": supplier_lead_days,
            "status": "REQUESTED",
            "confirmed_at": None,
            "estimated_ready_date": None,
            "actual_ready_date": None,
            "variance_days": None,
        }
    )
    insert("special_orders", rec)
    return created(serializers.special_order(rec))


@bp.get("/special-orders/<rec_id>")
@require(*GET_ALL)
def get_special_order(rec_id):
    return ok(serializers.special_order(fetch("special_orders", rec_id)))


@bp.get("/special-orders")
@require(*GET_ALL)
def list_special_orders():
    return list_response(
        db.special_orders.values(),
        serializers.special_order,
        {"order_id": "order_id", "order_line_id": "order_line_id"},
    )


@bp.post("/special-orders/<rec_id>/confirm")
@require("FulfillmentCoordinator", "StoreManager")
def confirm_special_order(rec_id):
    rec = fetch("special_orders", rec_id)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Special order is not REQUESTED")
    order = db.orders.get(rec["order_id"])
    if order is None or order["fulfillment_status"] != "CONFIRMED":
        raise err("ERR_ORDER_NOT_CONFIRMED", "Parent order is not CONFIRMED")
    rec["status"] = "CONFIRMED"
    rec["confirmed_at"] = db.clock
    rec["estimated_ready_date"] = db.clock + timedelta(days=rec["supplier_lead_days"])
    touch(rec)
    return ok(serializers.special_order(rec))


@bp.post("/special-orders/<rec_id>/complete")
@require("FulfillmentCoordinator", "StoreManager")
def complete_special_order(rec_id):
    rec = fetch("special_orders", rec_id)
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Special order is not CONFIRMED")
    rec["status"] = "READY"
    rec["actual_ready_date"] = db.clock
    rec["variance_days"] = floor_days(rec["actual_ready_date"], rec["estimated_ready_date"])
    touch(rec)
    return ok(serializers.special_order(rec))


# --------------------------- DesignConsult ---------------------------
@bp.post("/design-consults")
@require("Designer", "StoreManager")
def create_design_consult():
    body = get_body()
    trade_account_id = body.get("trade_account_id")
    if trade_account_id is None:
        raise err("ERR_INVALID_REQUEST", "trade_account_id is required")
    fk("trade_accounts", trade_account_id)
    order_id = body.get("order_id")
    if order_id is not None:
        fk("orders", order_id)
    room_type = req_str(body, "room_type")
    fee_cents = opt_int(body, "fee_cents", 0)
    check_designer_ownership(trade_account_id)
    rec = new_base()
    rec.update(
        {
            "trade_account_id": trade_account_id,
            "order_id": order_id,
            "room_type": room_type,
            "fee_cents": fee_cents,
            "status": "REQUESTED",
            "revision_count": 0,
        }
    )
    insert("design_consults", rec)
    return created(serializers.design_consult(rec))


@bp.get("/design-consults/<rec_id>")
@require(*GET_ALL)
def get_design_consult(rec_id):
    return ok(serializers.design_consult(fetch("design_consults", rec_id)))


@bp.get("/design-consults")
@require(*GET_ALL)
def list_design_consults():
    return list_response(
        db.design_consults.values(),
        serializers.design_consult,
        {"trade_account_id": "trade_account_id", "order_id": "order_id"},
    )


@bp.post("/design-consults/<rec_id>/submit-review")
@require("Designer", "StoreManager")
def submit_review(rec_id):
    rec = fetch("design_consults", rec_id)
    if rec["status"] not in ("REQUESTED", "REVISION"):
        raise err("ERR_INVALID_STATE", "Consult cannot be submitted for review from its state")
    check_designer_ownership(rec["trade_account_id"])
    rec["status"] = "IN_REVIEW"
    touch(rec)
    return ok(serializers.design_consult(rec))


@bp.post("/design-consults/<rec_id>/request-revision")
@require("Designer", "StoreManager")
def request_revision(rec_id):
    rec = fetch("design_consults", rec_id)
    if rec["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Consult is not IN_REVIEW")
    check_designer_ownership(rec["trade_account_id"])
    rec["status"] = "REVISION"
    rec["revision_count"] += 1
    touch(rec)
    return ok(serializers.design_consult(rec))


@bp.post("/design-consults/<rec_id>/approve")
@require("StoreManager")
def approve_design_consult(rec_id):
    rec = fetch("design_consults", rec_id)
    if rec["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Consult is not IN_REVIEW")
    rec["status"] = "APPROVED"
    touch(rec)
    return ok(serializers.design_consult(rec))
