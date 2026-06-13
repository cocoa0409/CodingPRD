"""FeeWaiver endpoints (nested under tow orders) with segregation of duties."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services import calc
from services import orders as order_svc
from services.serialize import public
from validators import paginate_and_respond, require_enum, require_int, sort_by_created

bp = Blueprint("fee_waivers", __name__)

REASONS = {"WRONGFUL_TOW", "HARDSHIP", "LAW_ENFORCEMENT_ERROR", "BILLING_DISPUTE"}


def get_order_or_404(order_id):
    o = db.tow_orders.get(order_id)
    if o is None:
        raise ApiError("ERR_NOT_FOUND", "Tow order not found")
    return o


def get_waiver_or_404(order_id, wid):
    w = db.fee_waivers.get(wid)
    if w is None or w["tow_order_id"] != order_id:
        raise ApiError("ERR_NOT_FOUND", "Fee waiver not found")
    return w


@bp.route("/tow-orders/<order_id>/fee-waivers", methods=["POST"])
def file_waiver(order_id):
    user_id, role = require_user_context()
    require_role(role, {"Claimant"})
    get_order_or_404(order_id)
    body = get_json_body()
    reason = require_enum(body, "reason", REASONS)
    requested_amount = require_int(body, "requested_amount_cents", minimum=1)
    waiver = {
        "tow_order_id": order_id,
        "reason": reason,
        "requested_amount_cents": requested_amount,
        "approved_amount_cents": None,
        "decided_by_user_id": None,
        "filed_by_user_id": user_id,
        "status": "REQUESTED",
    }
    db.stamp_create(waiver)
    db.fee_waivers[waiver["id"]] = waiver
    return object_response(public(waiver), 201)


@bp.route("/tow-orders/<order_id>/fee-waivers", methods=["GET"])
def list_waivers(order_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    items = [w for w in db.fee_waivers.values() if w["tow_order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_by_created(items)
    return paginate_and_respond([public(w) for w in items])


@bp.route("/tow-orders/<order_id>/fee-waivers/<wid>", methods=["GET"])
def get_waiver(order_id, wid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    get_order_or_404(order_id)
    w = get_waiver_or_404(order_id, wid)
    return object_response(public(w), 200)


@bp.route("/tow-orders/<order_id>/fee-waivers/<wid>/start-review", methods=["POST"])
def start_review(order_id, wid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    w = get_waiver_or_404(order_id, wid)
    if w["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Waiver is not REQUESTED")
    w["status"] = "UNDER_REVIEW"
    db.touch(w)
    return object_response(public(w), 200)


@bp.route("/tow-orders/<order_id>/fee-waivers/<wid>/approve", methods=["POST"])
def approve(order_id, wid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    order = get_order_or_404(order_id)
    w = get_waiver_or_404(order_id, wid)
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Waiver is not UNDER_REVIEW")
    if user_id == w["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from filer")
    order_svc.recompute(order)
    pre_waiver_balance = order["balance_due_cents"]
    cap = calc.waiver_cap(pre_waiver_balance)
    approved = min(w["requested_amount_cents"], cap)
    w["approved_amount_cents"] = approved
    w["decided_by_user_id"] = user_id
    w["status"] = "APPROVED"
    db.touch(w)
    order["waiver_credit_cents"] = order.get("waiver_credit_cents", 0) + approved
    order_svc.recompute(order)
    db.touch(order)
    return object_response(public(w), 200)


@bp.route("/tow-orders/<order_id>/fee-waivers/<wid>/deny", methods=["POST"])
def deny(order_id, wid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    get_order_or_404(order_id)
    w = get_waiver_or_404(order_id, wid)
    if w["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Waiver is not UNDER_REVIEW")
    if user_id == w["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "Decider must differ from filer")
    w["decided_by_user_id"] = user_id
    w["status"] = "DENIED"
    db.touch(w)
    return object_response(public(w), 200)


@bp.route("/tow-orders/<order_id>/fee-waivers/<wid>/withdraw", methods=["POST"])
def withdraw(order_id, wid):
    user_id, role = require_user_context()
    require_role(role, {"Claimant"})
    get_order_or_404(order_id)
    w = get_waiver_or_404(order_id, wid)
    if w["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", "Waiver is not REQUESTED")
    if user_id != w["filed_by_user_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "Only the filer may withdraw")
    w["status"] = "WITHDRAWN"
    db.touch(w)
    return object_response(public(w), 200)
