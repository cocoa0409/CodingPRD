"""ServiceAccount endpoints."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION,
    ERR_DUPLICATE_ACCOUNT_NUMBER, ERR_ACCOUNT_HAS_OPEN_INVESTIGATION,
    ERR_ACCOUNT_HAS_OPEN_WORK,
)
from middleware import require_roles, ALL_ROLES, body, req_str, opt_enum
from response import success, list_response, created_sorted
from serializers import ser_account
from services.cascades import cancel_pending_stops_for_account

bp = Blueprint("accounts", __name__)

OPEN_STOP_STATES = ("PENDING", "READ_CAPTURED", "NO_READ_PENDING", "SKIPPED_HAZARD")
OPEN_ORDER_STATES = ("OPEN", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "REWORK")
BLOCKING_INVESTIGATION_STATES = ("OPEN", "EVIDENCE_GATHERING", "PENDING_DISPOSITION", "CONFIRMED_THEFT")


def get_account(aid):
    a = db.accounts.get(aid)
    if not a:
        raise ApiError(ERR_NOT_FOUND, "ServiceAccount not found", 404)
    return a


@bp.route("/service-accounts", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    account_number = req_str(data, "account_number")
    service_address = req_str(data, "service_address")
    billing_cycle_code = req_str(data, "billing_cycle_code")
    estimation_method = opt_enum(
        data, "estimation_method",
        ("TRAILING_AVERAGE", "SAME_PERIOD_LAST_YEAR"),
        default="TRAILING_AVERAGE",
    )
    if any(a["account_number"] == account_number for a in db.accounts.values()):
        raise ApiError(ERR_DUPLICATE_ACCOUNT_NUMBER, "account_number already exists", 409)
    rec = {
        "account_number": account_number,
        "service_address": service_address,
        "billing_cycle_code": billing_cycle_code,
        "estimation_method": estimation_method,
        "account_status": "ACTIVE",
        "estimated_read_streak": 0,
    }
    stamp_new(rec)
    db.accounts[rec["id"]] = rec
    return success(ser_account(rec), code=201)


@bp.route("/service-accounts", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.accounts.values())
    for param in ("billing_cycle_code", "account_status", "current_meter_id"):
        val = request.args.get(param)
        if val is None:
            continue
        if param == "current_meter_id":
            from serializers import account_current_meter_id
            items = [a for a in items if account_current_meter_id(a["id"]) == val]
        else:
            items = [a for a in items if a[param] == val]
    return list_response([ser_account(a) for a in created_sorted(items)])


@bp.route("/service-accounts/<aid>", methods=["GET"])
def get_one(aid):
    require_roles(*ALL_ROLES)
    return success(ser_account(get_account(aid)), code=200)


@bp.route("/service-accounts/<aid>/suspend", methods=["POST"])
def suspend(aid):
    require_roles("MeterOpsAdmin")
    a = get_account(aid)
    if a["account_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Account is not ACTIVE", 409)
    a["account_status"] = "SUSPENDED"
    touch(a)
    cancel_pending_stops_for_account(aid)
    return success(ser_account(a), code=200)


@bp.route("/service-accounts/<aid>/reactivate", methods=["POST"])
def reactivate(aid):
    require_roles("MeterOpsAdmin")
    a = get_account(aid)
    if a["account_status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Account is not SUSPENDED", 409)
    blocked = any(
        i["service_account_id"] == aid
        and i["investigation_status"] in BLOCKING_INVESTIGATION_STATES
        for i in db.investigations.values()
    )
    if blocked:
        raise ApiError(
            ERR_ACCOUNT_HAS_OPEN_INVESTIGATION,
            "Account has a non-terminal investigation",
            409,
        )
    a["account_status"] = "ACTIVE"
    touch(a)
    return success(ser_account(a), code=200)


@bp.route("/service-accounts/<aid>/close", methods=["POST"])
def close(aid):
    require_roles("MeterOpsAdmin")
    a = get_account(aid)
    if a["account_status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Account cannot be closed from its state", 409)
    open_stops = any(
        s["service_account_id"] == aid and s["stop_status"] in OPEN_STOP_STATES
        for s in db.stops.values()
    )
    open_orders = any(
        w["service_account_id"] == aid and w["work_order_status"] in OPEN_ORDER_STATES
        for w in db.work_orders.values()
    )
    open_invs = any(
        i["service_account_id"] == aid and i["investigation_status"] != "CLOSED"
        for i in db.investigations.values()
    )
    if open_stops or open_orders or open_invs:
        raise ApiError(
            ERR_ACCOUNT_HAS_OPEN_WORK,
            "Account has open stops, work orders, or investigations",
            409,
        )
    a["account_status"] = "CLOSED"
    touch(a)
    return success(ser_account(a), code=200)
