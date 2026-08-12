from flask import Blueprint

import services as svc
from clock import now
from errors import ApiError, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    require_dt,
    require_enum,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("vacation", __name__)

SKIP_REASONS = {"VACATION", "WEATHER_HOLD", "CUSTOMER_REQUEST", "HOA_DIRECTIVE"}


def _owned_window(wid, uid):
    w = lookup(svc.vacation_windows, wid, "VacationWindow")
    sub = svc.subscriptions.get(w["subscription_id"])
    if sub is None or sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only act on their own vacation windows")
    return w


@bp.post("/api/vacation-windows")
def create_vacation_window():
    uid, role = auth("Customer", "OperationsManager")
    data = get_body()
    subscription_id = require(data, "subscription_id", str)
    start_date = require_dt(data, "start_date")
    end_date = require_dt(data, "end_date")
    reason = require_enum(data, "skip_reason", SKIP_REASONS)
    sub = lookup_fk(svc.subscriptions, subscription_id, "Subscription")
    if role == "Customer":
        if sub["customer_id"] != uid:
            raise err_unauthorized("Customers may only create windows on their own subscriptions")
        customer = svc.customers.get(sub["customer_id"])
        if customer is not None and customer["account_status"] != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409,
                           "Customer.account_status must be ACTIVE")
    if start_date > end_date or start_date.date() < now().date():
        raise ApiError("ERR_INVALID_WINDOW", 422,
                       "start_date must be <= end_date and not in the past")
    for w in svc.vacation_windows.values():
        if (
            w["subscription_id"] == sub["id"]
            and w["window_status"] in ("SCHEDULED", "APPLIED")
            and start_date.date() <= w["end_date"].date()
            and w["start_date"].date() <= end_date.date()
        ):
            raise ApiError("ERR_WINDOW_OVERLAP", 409,
                           "Window overlaps an existing SCHEDULED/APPLIED window")
    rec = svc.new_record()
    rec.update(
        {
            "subscription_id": sub["id"],
            "start_date": start_date,
            "end_date": end_date,
            "skip_reason": reason,
            "window_status": "SCHEDULED",
        }
    )
    svc.vacation_windows[rec["id"]] = rec
    return ok_object(svc.ser_vacation_window(rec), status=201)


@bp.get("/api/vacation-windows/<wid>")
def get_vacation_window(wid):
    uid, role = auth("Customer", "OperationsManager")
    w = lookup(svc.vacation_windows, wid, "VacationWindow")
    if role == "Customer":
        sub = svc.subscriptions.get(w["subscription_id"])
        if sub is None or sub["customer_id"] != uid:
            raise err_unauthorized("Customers may only access their own vacation windows")
    return ok_object(svc.ser_vacation_window(w))


@bp.get("/api/subscriptions/<sid>/vacation-windows")
def list_subscription_windows(sid):
    uid, role = auth("Customer", "OperationsManager")
    sub = lookup(svc.subscriptions, sid, "Subscription")
    if role == "Customer" and sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own subscriptions")
    limit, offset = parse_pagination()
    records = [w for w in svc.vacation_windows.values() if w["subscription_id"] == sid]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_vacation_window(w) for w in page], total, limit, offset)


@bp.post("/api/vacation-windows/<wid>/cancel")
def cancel_vacation_window(wid):
    uid, role = auth("Customer", "OperationsManager")
    w = lookup(svc.vacation_windows, wid, "VacationWindow")
    if role == "Customer":
        sub = svc.subscriptions.get(w["subscription_id"])
        if sub is None or sub["customer_id"] != uid:
            raise err_unauthorized("Customers may only cancel their own vacation windows")
    if w["window_status"] != "SCHEDULED":
        raise err_invalid_state("cancel is only valid from SCHEDULED")
    if now() >= w["start_date"]:
        raise ApiError("ERR_WINDOW_ALREADY_STARTED", 409,
                       "Cannot cancel a window at or after its start_date")
    w["window_status"] = "CANCELLED"
    svc.bump(w)
    return ok_object(svc.ser_vacation_window(w))
