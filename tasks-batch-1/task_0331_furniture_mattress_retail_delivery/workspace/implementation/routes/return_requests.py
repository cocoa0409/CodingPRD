"""ReturnRequest endpoints incl. branching-with-revert machine (PRD §3.10)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import helpers
import response
from errors import err
from middleware import get_auth, require_role
from services import calculations as calc
from services import domain, serializers

bp = Blueprint("return_requests", __name__)

REASONS = {"DAMAGED", "DEFECTIVE", "CHANGED_MIND"}


@bp.post("/return-requests")
def file_return():
    user_id, role = get_auth()
    require_role(role, {"Customer", "SalesAssociate", "StoreManager"})
    body = helpers.get_body()

    # Existence (4): resolve the covered line (needed to evaluate ownership transitively).
    order_line_id = helpers.require_str(body, "order_line_id")
    line = helpers.fetch(db.order_lines, order_line_id)
    order = db.orders.get(line["order_id"])

    # Ownership (3): a Customer may only file on their own order's line.
    if role == "Customer":
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")

    # Shape (5).
    reason = helpers.require_enum(body, "reason", REASONS)

    rec = {
        "order_line_id": order_line_id,
        "order_id": line["order_id"],
        "reason": reason,
        "restocking_fee_cents": None,
        "refund_amount_cents": None,
        "filed_on": clock.iso_now(),
        "status": "REQUESTED",
    }
    helpers.stamp_create(rec)
    db.return_requests[rec["id"]] = rec
    return response.object_response(serializers.return_request(rec), status=201)


@bp.get("/return-requests/<rid>")
def get_return(rid):
    user_id, role = get_auth()
    require_role(role, {"Customer", "SalesAssociate", "StoreManager"})
    rec = helpers.fetch(db.return_requests, rid)
    if role == "Customer":
        order = db.orders.get(rec["order_id"])
        if order is None or user_id != order["customer_id"]:
            raise err("ERR_FORBIDDEN_NOT_OWNER", "Not the owning customer.")
    return response.object_response(serializers.return_request(rec))


@bp.post("/return-requests/<rid>/approve")
def approve_return(rid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    rec = helpers.fetch(db.return_requests, rid)

    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Return is not REQUESTED.")
    line = db.order_lines.get(rec["order_line_id"])
    if line is None or line["status"] != "ACTIVE":
        raise err("ERR_LINE_NOT_RETURNABLE", "Covered line is not ACTIVE.")

    # Return-window gate: filed_on <= delivered_on + window_days (inclusive).
    delivered_on = line.get("_delivered_on")
    product = db.products.get(line["product_id"])
    category = product["category"] if product else None
    window_days = calc.return_window_days(category)
    if delivered_on is None:
        # Line never delivered -> window cannot be satisfied.
        raise err("ERR_RETURN_WINDOW_CLOSED", "Return window is closed.")
    delivered_dt = clock.parse_iso(delivered_on)
    filed_dt = clock.parse_iso(rec["filed_on"])
    deadline = delivered_dt.date() + timedelta(days=window_days)
    if filed_dt.date() > deadline:
        raise err("ERR_RETURN_WINDOW_CLOSED", "Return filed after the return window.")

    gross = line["line_total_cents"]
    restocking_fee, refund = calc.return_refund(gross, rec["reason"])
    rec["restocking_fee_cents"] = restocking_fee
    rec["refund_amount_cents"] = refund
    rec["status"] = "APPROVED"
    helpers.touch(rec)
    return response.object_response(serializers.return_request(rec))


@bp.post("/return-requests/<rid>/reject")
def reject_return(rid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    rec = helpers.fetch(db.return_requests, rid)
    if rec["status"] not in ("REQUESTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Return is not in a rejectable state.")
    rec["status"] = "REJECTED"
    helpers.touch(rec)
    return response.object_response(serializers.return_request(rec))


@bp.post("/return-requests/<rid>/refund")
def refund_return(rid):
    _, role = get_auth()
    require_role(role, {"StoreManager"})
    rec = helpers.fetch(db.return_requests, rid)
    if rec["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Return is not APPROVED.")

    # CASCADE: covered line -> RETURNED; its ACTIVE protection plan -> VOIDED;
    # order.amount_refunded_cents += refund_amount_cents.
    line = db.order_lines.get(rec["order_line_id"])
    if line is not None:
        line["status"] = "RETURNED"
        helpers.touch(line)
        for plan in domain.active_protection_plans_for_line(line["id"]):
            plan["status"] = "VOIDED"
            helpers.touch(plan)

    order = db.orders.get(rec["order_id"])
    if order is not None:
        order["amount_refunded_cents"] += rec["refund_amount_cents"]
        helpers.touch(order)

    rec["status"] = "REFUNDED"
    helpers.touch(rec)
    return response.object_response(serializers.return_request(rec))
