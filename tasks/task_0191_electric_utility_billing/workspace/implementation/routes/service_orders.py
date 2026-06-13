"""ServiceOrder endpoints: complete, cancel, and reads (PRD §3.6)."""
from flask import Blueprint, request

from db import db, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import paginate, parse_pagination

bp = Blueprint("service_orders", __name__)

READ_ROLES = {"BillingOperator", "FieldDispatcher"}


@bp.route("/service-orders/<order_id>/complete", methods=["POST"])
def complete_order(order_id):
    _, role = authenticate()
    require_roles(role, {"FieldDispatcher"})
    so = db.service_orders.get(order_id)
    if so is None:
        raise err("ERR_NOT_FOUND", "Service order not found.")

    # State check (priority 9) before order/account match (priority 10).
    if so["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED order can be completed.")

    account = db.accounts.get(so["account_id"])
    expected = "DISCONNECT_PENDING" if so["order_type"] == "DISCONNECT" else "RECONNECT_PENDING"
    if account is None or account["service_status"] != expected:
        raise err(
            "ERR_ORDER_ACCOUNT_MISMATCH",
            "Order type does not match the account's pending service status.",
        )

    so["status"] = "COMPLETED"
    touch(so)

    # Advance the account's service dimension.
    if so["order_type"] == "DISCONNECT":
        account["service_status"] = "DISCONNECTED"
    else:
        account["service_status"] = "ACTIVE"
    touch(account)  # increments Account.version (PRD §3.6)
    return success(ser.service_order(so), status=200)


@bp.route("/service-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator", "FieldDispatcher"})
    so = db.service_orders.get(order_id)
    if so is None:
        raise err("ERR_NOT_FOUND", "Service order not found.")
    if so["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED order can be cancelled.")

    so["status"] = "CANCELLED"
    touch(so)

    # Cancelling a still-pending DISCONNECT reverts the account to ACTIVE.
    account = db.accounts.get(so["account_id"])
    if (
        so["order_type"] == "DISCONNECT"
        and account is not None
        and account["service_status"] == "DISCONNECT_PENDING"
    ):
        account["service_status"] = "ACTIVE"
        touch(account)  # increments Account.version (PRD §3.6)
    return success(ser.service_order(so), status=200)


@bp.route("/service-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    so = db.service_orders.get(order_id)
    if so is None:
        raise err("ERR_NOT_FOUND", "Service order not found.")
    return success(ser.service_order(so), status=200)


@bp.route("/service-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    order_type = request.args.get("order_type")
    items = list(db.service_orders.values())
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if order_type is not None:
        items = [s for s in items if s["order_type"] == order_type]
    page, pagination = paginate(items)
    return success(
        [ser.service_order(s) for s in page], status=200, pagination=pagination
    )
