"""Order, ServiceExecution, RecurringOrder, AbnormalEvent, OrderRating routes."""
from flask import Blueprint, request

from db import store
from errors import ERR_NOT_FOUND, raise_error
from response import success_response
from middleware import require_roles
from services import orders as ord_svc
from services import recurring as rec_svc
from services import ratings as rate_svc
from services import sweeps as sweeps_svc
from services.utils import parse_pagination, paginate


bp = Blueprint("orders", __name__)


# ---------- Orders ----------
@bp.route("/dsd/orders", methods=["POST"])
def create_order():
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    body = request.get_json(silent=True) or {}
    o = ord_svc.create_order(body, role, user_id)
    return success_response(o, http_status=201)


@bp.route("/dsd/orders/<oid>", methods=["PATCH"])
def patch_order(oid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    o = ord_svc.patch_order(oid, body, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/submit", methods=["POST"])
def submit_order(oid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.submit_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    role, user_id = require_roles({"PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.dispatch_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/reassign", methods=["POST"])
def reassign_order(oid):
    role, user_id = require_roles({"PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    o = ord_svc.reassign_order(oid, body, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/accept", methods=["POST"])
def accept_order(oid):
    role, user_id = require_roles({"ServicePersonnel"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.accept_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/reject", methods=["POST"])
def reject_order(oid):
    role, user_id = require_roles({"ServicePersonnel"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.reject_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/checkin", methods=["POST"])
def checkin_order(oid):
    role, user_id = require_roles({"ServicePersonnel"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    o = ord_svc.checkin_order(oid, body, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/execution", methods=["PATCH"])
def patch_execution(oid):
    role, user_id = require_roles({"ServicePersonnel"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    ex = ord_svc.patch_execution(oid, body, role, user_id)
    return success_response(ex)


@bp.route("/dsd/orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    role, user_id = require_roles({"ServicePersonnel"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.complete_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/customer-accept", methods=["POST"])
def customer_accept(oid):
    role, user_id = require_roles({"Customer"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.customer_accept_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.cancel_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>/refund", methods=["POST"])
def refund_order(oid):
    role, user_id = require_roles({"PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = ord_svc.refund_order(oid, role, user_id)
    return success_response(o)


@bp.route("/dsd/orders/<oid>", methods=["GET"])
def get_order(oid):
    role, user_id = require_roles({"Customer", "ServicePersonnel", "PlatformOperator"})
    sweeps_svc.realize_dispatch_expiries()
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    o = store.orders[oid]
    if role == "Customer" and user_id != o["customer_id"]:
        raise_error(ERR_NOT_FOUND, "Order not found")
    if role == "ServicePersonnel" and user_id != o.get("assigned_personnel_id"):
        raise_error(ERR_NOT_FOUND, "Order not found")
    return success_response(o)


@bp.route("/dsd/orders", methods=["GET"])
def list_orders():
    role, user_id = require_roles({"Customer", "ServicePersonnel", "PlatformOperator"})
    sweeps_svc.realize_dispatch_expiries()
    limit, offset = parse_pagination()
    items = list(store.orders.values())
    if role == "Customer":
        items = [x for x in items if x["customer_id"] == user_id]
    elif role == "ServicePersonnel":
        items = [x for x in items if x.get("assigned_personnel_id") == user_id]
    cust_f = request.args.get("customer_id")
    pers_f = request.args.get("assigned_personnel_id")
    status_f = request.args.get("status")
    if cust_f:
        items = [x for x in items if x["customer_id"] == cust_f]
    if pers_f:
        items = [x for x in items if x.get("assigned_personnel_id") == pers_f]
    if status_f:
        items = [x for x in items if x["status"] == status_f]
    window, page = paginate(items, limit, offset)
    return success_response(window, pagination=page)


# ---------- Recurring Orders ----------
@bp.route("/dsd/recurring-orders", methods=["POST"])
def create_recurring():
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    body = request.get_json(silent=True) or {}
    ro = rec_svc.create_recurring_order(body, role, user_id)
    return success_response(ro, http_status=201)


@bp.route("/dsd/recurring-orders/<rid>/pause", methods=["POST"])
def pause_recurring(rid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    ro = rec_svc.pause_recurring(rid, role, user_id)
    return success_response(ro)


@bp.route("/dsd/recurring-orders/<rid>/resume", methods=["POST"])
def resume_recurring(rid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    ro = rec_svc.resume_recurring(rid, role, user_id)
    return success_response(ro)


@bp.route("/dsd/recurring-orders/<rid>/terminate", methods=["POST"])
def terminate_recurring(rid):
    role, user_id = require_roles({"Customer", "PlatformOperator"})
    ro = rec_svc.terminate_recurring(rid, role, user_id)
    return success_response(ro)


# ---------- Abnormal Event ----------
@bp.route("/dsd/orders/<oid>/abnormal-events", methods=["POST"])
def report_abnormal(oid):
    role, user_id = require_roles({"Customer", "ServicePersonnel", "PlatformOperator"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    event, _claim = rate_svc.create_abnormal_event(oid, body, role, user_id)
    return success_response(event, http_status=201)


# ---------- Rating ----------
@bp.route("/dsd/orders/<oid>/rate", methods=["POST"])
def rate_order(oid):
    role, user_id = require_roles({"Customer"})
    if oid not in store.orders:
        raise_error(ERR_NOT_FOUND, "Order not found")
    body = request.get_json(silent=True) or {}
    r = rate_svc.create_rating(oid, body, role, user_id)
    return success_response(r, http_status=201)


@bp.route("/dsd/ratings/<rid>/close-investigation", methods=["POST"])
def close_inv(rid):
    require_roles({"PlatformOperator"})
    r = rate_svc.close_investigation(rid)
    return success_response(r)
