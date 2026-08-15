"""RepairOrder endpoints (PRD §3.6, §3.7)."""
from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt
from errors import err_not_found, err_forbidden, ApiError
from helpers import (body, req_str, opt_str, opt_int, req_int, req_dt,
                     paginate, sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import repair_order as ser
import services

bp = Blueprint("repair_orders", __name__)


def _get_ro(rid):
    ro = store.repair_orders.get(rid)
    if ro is None:
        raise err_not_found("REPAIR_ORDER")
    return ro


@bp.post("/dealership/repair-orders")
def create_ro():
    caller(["ServiceAdvisor"])
    data = body()
    account_id = req_str(data, "customer_account_id")
    concern = req_str(data, "concern")
    promised = req_dt(data, "promised_ready_at")
    unit_id = opt_str(data, "unit_id")
    external_vin = opt_str(data, "external_vin")
    rate = opt_int(data, "labor_rate_cents", 16500, minimum=1)

    if account_id not in store.customer_accounts:
        raise err_not_found("CUSTOMER_ACCOUNT")
    if unit_id is not None and unit_id not in store.units:
        raise err_not_found("UNIT")
    # Vehicle reference (13): exactly one of unit_id / external_vin.
    if (unit_id is None) == (external_vin is None):
        raise ApiError("ERR_VEHICLE_REFERENCE_REQUIRED", 422,
                       "Exactly one of unit_id / external_vin is required")

    ro = {
        "customer_account_id": account_id,
        "unit_id": unit_id,
        "external_vin": external_vin,
        "concern": concern,
        "_promised_dt": promised,
        "labor_rate_cents": rate,
        "auth_status": "DRAFT",
        "work_status": "OPEN",
        "labor_sum_cents": 0,
        "parts_sum_cents": 0,
        "discount_cents": 0,
        "shop_supplies_fee_cents": 0,
        "warranty_covered_cents": 0,
        "customer_due_cents": 0,
        "downtime_penalty_cents": 0,
        "_work_started_dt": None,
        "_completed_dt": None,
        "sla_breached": False,
    }
    stamp_new(ro)
    store.repair_orders[ro["id"]] = ro
    return success(ser(ro), status=201)


@bp.get("/dealership/repair-orders")
def list_ros():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.repair_orders.values()), [
        ("customer_account_id", request.args.get("customer_account_id")),
        ("unit_id", request.args.get("unit_id")),
        ("auth_status", request.args.get("auth_status")),
        ("work_status", request.args.get("work_status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(r) for r in page], meta)


@bp.get("/dealership/repair-orders/<rid>")
def get_ro(rid):
    caller(ALL_ROLES)
    return success(ser(_get_ro(rid)))


@bp.post("/dealership/repair-orders/<rid>/submit-estimate")
def submit_estimate(rid):
    caller(["ServiceAdvisor"])
    ro = _get_ro(rid)
    if ro["auth_status"] != "DRAFT":
        raise ApiError("ERR_RO_NOT_AWAITING_CUSTOMER", 409,
                       "Submit requires auth_status DRAFT")
    if not services.ro_lines(ro["id"]):
        raise ApiError("ERR_RO_STATE", 409,
                       "Submit requires at least one repair order line")
    ro["auth_status"] = "PENDING_APPROVAL"
    touch(ro)
    return success(ser(ro))


def _customer_estimate_action(rid, target):
    uid, _ = caller(["FleetCustomer"])
    ro = _get_ro(rid)
    if uid != ro["customer_account_id"]:
        raise err_forbidden(
            "FleetCustomer may only act on its own account's repair orders")
    if ro["auth_status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_RO_NOT_AWAITING_CUSTOMER", 409,
                       "Action requires auth_status PENDING_APPROVAL")
    ro["auth_status"] = target
    touch(ro)
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/approve-estimate")
def approve_estimate(rid):
    return _customer_estimate_action(rid, "APPROVED")


@bp.post("/dealership/repair-orders/<rid>/decline-estimate")
def decline_estimate(rid):
    return _customer_estimate_action(rid, "DECLINED")


@bp.post("/dealership/repair-orders/<rid>/revise")
def revise_ro(rid):
    caller(["ServiceAdvisor"])
    ro = _get_ro(rid)
    if ro["auth_status"] != "DECLINED":
        raise ApiError("ERR_RO_STATE", 409,
                       "Revise requires auth_status DECLINED")
    if ro["work_status"] not in ("OPEN", "SCHEDULED"):
        raise ApiError("ERR_RO_STATE", 409,
                       "Revise requires work_status OPEN or SCHEDULED")
    ro["auth_status"] = "DRAFT"
    touch(ro)
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/start-work")
def start_work(rid):
    caller(["ServiceAdvisor"])
    ro = _get_ro(rid)
    if ro["auth_status"] != "APPROVED":
        raise ApiError("ERR_RO_NOT_APPROVED", 409,
                       "Start work requires auth_status APPROVED")
    if ro["work_status"] not in ("OPEN", "SCHEDULED"):
        raise ApiError("ERR_RO_STATE", 409,
                       "Start work requires work_status OPEN or SCHEDULED")
    checked_in = any(
        b for b in store.service_bookings.values()
        if b["repair_order_id"] == ro["id"] and b["status"] == "CHECKED_IN")
    if not checked_in:
        raise ApiError("ERR_BOOKING_NOT_CHECKED_IN", 409,
                       "Start work requires a CHECKED_IN booking")
    ro["_work_started_dt"] = now_dt()
    ro["work_status"] = "IN_PROGRESS"
    touch(ro)
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/complete-work")
def complete_work(rid):
    caller(["ServiceAdvisor"])
    ro = _get_ro(rid)
    if ro["work_status"] != "IN_PROGRESS":
        raise ApiError("ERR_RO_STATE", 409,
                       "Complete work requires work_status IN_PROGRESS")
    now = now_dt()
    ro["_completed_dt"] = now
    ro["downtime_penalty_cents"] = services.downtime_penalty(
        ro, now, ro["_promised_dt"])
    ro["work_status"] = "COMPLETED"
    services.recompute_ro_totals(ro)
    touch(ro)
    for b in store.service_bookings.values():
        if b["repair_order_id"] == ro["id"] and b["status"] == "CHECKED_IN":
            b["status"] = "COMPLETED"
            touch(b)
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/invoice")
def invoice_ro(rid):
    caller(["ServiceManager"])
    ro = _get_ro(rid)
    if ro["work_status"] != "COMPLETED":
        raise ApiError("ERR_RO_STATE", 409,
                       "Invoice requires work_status COMPLETED")
    services.recompute_ro_totals(ro)
    account = store.customer_accounts.get(ro["customer_account_id"])
    if account is not None:
        if account["status"] != "ACTIVE":
            raise ApiError("ERR_ACCOUNT_ON_CREDIT_HOLD", 409,
                           "Account is on credit hold or closed")
        if account["account_type"] == "FLEET":
            if (ro["customer_due_cents"] + account["open_ar_cents"]
                    > account["credit_limit_cents"]):
                raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                               "Invoice would exceed the account credit limit")
    ro["work_status"] = "INVOICED"
    touch(ro)
    if account is not None:
        services.adjust_open_ar(account, ro["customer_due_cents"])
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/post-payment")
def post_payment(rid):
    caller(["Controller"])
    data = body()
    amount = req_int(data, "amount_cents")
    ro = _get_ro(rid)
    if ro["work_status"] != "INVOICED":
        raise ApiError("ERR_RO_STATE", 409,
                       "Post payment requires work_status INVOICED")
    if amount != ro["customer_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "Payment must equal customer_due_cents exactly")
    ro["work_status"] = "PAID"
    touch(ro)
    account = store.customer_accounts.get(ro["customer_account_id"])
    if account is not None:
        services.adjust_open_ar(account, -amount)
    return success(ser(ro))


@bp.post("/dealership/repair-orders/<rid>/cancel")
def cancel_ro(rid):
    caller(["ServiceAdvisor"])
    ro = _get_ro(rid)
    if ro["work_status"] in ("INVOICED", "PAID", "CANCELLED"):
        raise ApiError("ERR_RO_STATE", 409,
                       "Cannot cancel an invoiced, paid, or cancelled order")
    ro["auth_status"] = "CANCELLED"
    ro["work_status"] = "CANCELLED"
    touch(ro)
    for b in store.service_bookings.values():
        if (b["repair_order_id"] == ro["id"]
                and b["status"] in ("BOOKED", "CHECKED_IN")):
            b["status"] = "CANCELLED"
            touch(b)
    return success(ser(ro))
