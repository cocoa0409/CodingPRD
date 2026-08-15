"""ShutoffOrder endpoints (PRD §3.7)."""

from flask import Blueprint

import db
from errors import (not_found, ApiError, ERR_ACCOUNT_NOT_CONNECTED,
                    ERR_SHUTOFF_BLOCKED_BY_MEDICAL,
                    ERR_SHUTOFF_BLOCKED_BY_MORATORIUM, ERR_DPA_KEPT_CURRENT,
                    ERR_NOTICE_PERIOD_TOO_SHORT, ERR_OPEN_SHUTOFF_ORDER_EXISTS,
                    ERR_NOT_SHUTOFF_ELIGIBLE, ERR_ORDER_NOT_EXECUTABLE,
                    ERR_INVALID_STATE)
from middleware import authenticate, check_ownership
from response import success_object, success_list
from serializers import shutoff_order as ser_order
from services.common import (touch_account, covering_certificate, open_order,
                             kept_current_active_dpa, delinquency_tier,
                             SHUTOFF_MIN_ARREARAGE_CENTS)
from services.reconnect import snapshot_fee_schedule
from validate import (get_body, validate_shape, parse_pagination, parse_filters,
                      paginate, sort_by_creation)

bp = Blueprint("orders", __name__)

NOTICE_DAYS = 15
ORDER_STATUSES = {"SCHEDULED", "BLOCKED", "EXECUTED", "CANCELLED"}
GET_ROLES = ["Customer", "CustomerServiceRep", "ProgramAdmin", "FieldCrew"]
LIST_ROLES = ["CustomerServiceRep", "ProgramAdmin", "FieldCrew"]


def get_order_or_404(order_id):
    o = db.shutoff_orders.get(order_id)
    if o is None:
        raise not_found("Shutoff order not found")
    return o


def _medical_block_check(account):
    if covering_certificate(account["id"]) is not None:
        raise ApiError(ERR_SHUTOFF_BLOCKED_BY_MEDICAL, 422,
                       "An ACTIVE medical certificate covers the clock date")


def _weather_block_check(account):
    if account["protection_status"] == "WEATHER_MORATORIUM":
        raise ApiError(ERR_SHUTOFF_BLOCKED_BY_MORATORIUM, 422,
                       "Account is under a weather moratorium")


@bp.route("/assistance/shutoff-orders", methods=["POST"])
def create_order():
    authenticate(["ProgramAdmin"])
    body = validate_shape(get_body(allow_empty=False), [
        ("account_id", "string", True, None),
        ("scheduled_date", "datetime", True, None),
        ("reason", "enum", False, {"NONPAYMENT"}),
    ])
    account = db.accounts.get(body["account_id"])
    if account is None:
        raise not_found("Account not found")
    scheduled = db.parse_datetime(body["scheduled_date"]).date()
    # pinned validation chain (PRD §3.7)
    if account["service_status"] == "DISCONNECTED":
        raise ApiError(ERR_ACCOUNT_NOT_CONNECTED, 409,
                       "Manual shutoff creation requires a non-DISCONNECTED account")
    _medical_block_check(account)
    _weather_block_check(account)
    if kept_current_active_dpa(account["id"]) is not None:
        raise ApiError(ERR_DPA_KEPT_CURRENT, 422,
                       "A kept-current ACTIVE DPA blocks shutoff creation")
    if scheduled < db.add_days(db.CLOCK.date(), NOTICE_DAYS):
        raise ApiError(ERR_NOTICE_PERIOD_TOO_SHORT, 422,
                       "scheduled_date must be at least 15 days after the clock date")
    if open_order(account["id"]) is not None:
        raise ApiError(ERR_OPEN_SHUTOFF_ORDER_EXISTS, 422,
                       "An open shutoff order already exists on the account")
    if not (delinquency_tier(account) in ("DELINQUENT", "SEVERELY_DELINQUENT")
            and account["arrearage_balance_cents"] >= SHUTOFF_MIN_ARREARAGE_CENTS):
        raise ApiError(ERR_NOT_SHUTOFF_ELIGIBLE, 422,
                       "Account must be DELINQUENT|SEVERELY_DELINQUENT with "
                       "arrearage >= 10000")
    order = {
        "id": db.new_id(),
        "account_id": account["id"],
        "reason": body.get("reason") or "NONPAYMENT",
        "scheduled_date": scheduled,
        "status": "SCHEDULED",
        "origin": "MANUAL",
        "blocked_reason": None,
        "executed_at": None,
    }
    db.stamp_common(order)
    db.shutoff_orders[order["id"]] = order
    account["service_status"] = "DISCONNECT_PENDING"
    touch_account(account)
    return success_object(ser_order(order), status=201)


@bp.route("/assistance/shutoff-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    actor = authenticate(GET_ROLES)
    o = db.shutoff_orders.get(order_id)
    if o is not None:
        check_ownership(actor, o["account_id"])
    if o is None:
        raise not_found("Shutoff order not found")
    return success_object(ser_order(o))


@bp.route("/assistance/shutoff-orders", methods=["GET"])
def list_orders():
    authenticate(LIST_ROLES)
    limit, offset = parse_pagination()
    filters = parse_filters({"account_id": "str", "status": ORDER_STATUSES})
    items = sort_by_creation(db.shutoff_orders.values())
    if "account_id" in filters:
        items = [x for x in items if x["account_id"] == filters["account_id"]]
    if "status" in filters:
        items = [x for x in items if x["status"] == filters["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([ser_order(x) for x in page], limit, offset, total)


@bp.route("/assistance/shutoff-orders/<order_id>/execute", methods=["POST"])
def execute_order(order_id):
    authenticate(["FieldCrew"])
    get_body()  # body optional; ignored
    o = get_order_or_404(order_id)
    account = db.accounts.get(o["account_id"])
    if (o["status"] != "SCHEDULED"
            or db.CLOCK.date() < o["scheduled_date"]
            or account is None
            or account["service_status"] != "DISCONNECT_PENDING"):
        raise ApiError(ERR_ORDER_NOT_EXECUTABLE, 409,
                       "Execute requires status SCHEDULED, scheduled_date reached, "
                       "and account DISCONNECT_PENDING")
    # protection is re-checked at execution time (PRD §3.7)
    _medical_block_check(account)
    _weather_block_check(account)
    o["status"] = "EXECUTED"
    o["executed_at"] = db.CLOCK.now()
    db.touch(o)
    account["service_status"] = "DISCONNECTED"
    snapshot_fee_schedule(account)
    touch_account(account)
    return success_object(ser_order(o))


@bp.route("/assistance/shutoff-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    authenticate(["CustomerServiceRep", "ProgramAdmin"])
    o = get_order_or_404(order_id)
    if o["status"] not in ("SCHEDULED", "BLOCKED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cancel requires order status SCHEDULED|BLOCKED")
    o["status"] = "CANCELLED"
    o["blocked_reason"] = None
    db.touch(o)
    account = db.accounts.get(o["account_id"])
    if account is not None and open_order(account["id"]) is None \
            and account["service_status"] == "DISCONNECT_PENDING":
        account["service_status"] = "CONNECTED"
        touch_account(account)
    return success_object(ser_order(o))
