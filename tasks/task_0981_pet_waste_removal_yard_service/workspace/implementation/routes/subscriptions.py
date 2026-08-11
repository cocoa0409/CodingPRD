from flask import Blueprint, request

import services as svc
from clock import now
from errors import ApiError, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("subscriptions", __name__)


def _owned_subscription(sid, uid):
    sub = lookup(svc.subscriptions, sid, "Subscription")
    if sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only act on their own subscriptions")
    return sub


def _check_account_active(customer):
    if customer is not None and customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409,
                       "Customer.account_status must be ACTIVE")


def _check_scope(plan, yard):
    if plan["applies_to_multifamily"] != yard["is_multifamily_common_area"]:
        raise ApiError("ERR_PLAN_SCOPE_MISMATCH", 422,
                       "Plan applies_to_multifamily disagrees with yard scope")


@bp.post("/api/subscriptions")
def create_subscription():
    uid, role = auth("OperationsManager", "Customer")
    data = get_body()
    customer_id = require(data, "customer_id", str)
    yard_id = require(data, "yard_id", str)
    plan_id = require(data, "plan_id", str)
    customer = lookup_fk(svc.customers, customer_id, "Customer")
    yard = lookup_fk(svc.yards, yard_id, "Yard")
    plan = lookup_fk(svc.plans, plan_id, "SubscriptionPlan")
    if role == "Customer":
        if customer_id != uid:
            raise err_unauthorized("Customers may only create their own subscriptions")
        _check_account_active(customer)
    _check_scope(plan, yard)
    if yard["customer_id"] != customer_id:
        raise ApiError("ERR_YARD_OWNERSHIP_MISMATCH", 422,
                       "Yard does not belong to the referenced customer")
    rec = svc.new_record()
    rec.update(
        {
            "customer_id": customer_id,
            "yard_id": yard_id,
            "plan_id": plan_id,
            "status": "DRAFT",
            "started_on": None,
            "next_billing_anchor_date": None,
            "monthly_fee_cents_snapshot": None,
            "pending_plan_change_id": None,
            "plan_change_effective_date": None,
        }
    )
    svc.subscriptions[rec["id"]] = rec
    return ok_object(svc.ser_subscription(rec), status=201)


@bp.get("/api/subscriptions/<sid>")
def get_subscription(sid):
    uid, role = auth("OperationsManager", "Customer", "BillingAdmin")
    svc.apply_pending_plan_changes()
    sub = lookup(svc.subscriptions, sid, "Subscription")
    if role == "Customer" and sub["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own subscriptions")
    return ok_object(svc.ser_subscription(sub))


@bp.get("/api/subscriptions")
def list_subscriptions():
    uid, role = auth("OperationsManager", "Customer", "BillingAdmin")
    svc.apply_pending_plan_changes()
    limit, offset = parse_pagination()
    records = list(svc.subscriptions.values())
    if role == "Customer":
        requested = request.args.get("customer_id")
        if requested is not None and requested != uid:
            raise err_unauthorized("Customers may only list their own subscriptions")
        records = [s for s in records if s["customer_id"] == uid]
    else:
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            records = [s for s in records if s["customer_id"] == customer_id]
    yard_id = request.args.get("yard_id")
    if yard_id is not None:
        records = [s for s in records if s["yard_id"] == yard_id]
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        records = [s for s in records if s["plan_id"] == plan_id]
    pending = request.args.get("pending_plan_change_id")
    if pending is not None:
        records = [s for s in records if s["pending_plan_change_id"] == pending]
    status = request.args.get("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_subscription(s) for s in page], total, limit, offset)


@bp.post("/api/subscriptions/<sid>/activate")
def activate_subscription(sid):
    uid, _ = auth("Customer")
    sub = _owned_subscription(sid, uid)
    if sub["status"] != "DRAFT":
        raise err_invalid_state("activate is only valid from DRAFT")
    customer = svc.customers.get(sub["customer_id"])
    _check_account_active(customer)
    yard = svc.yards.get(sub["yard_id"])
    profile = svc.access_profile_of_yard(sub["yard_id"]) if yard else None
    if profile is None or profile["access_status"] != "VERIFIED":
        raise ApiError("ERR_ACCESS_NOT_VERIFIED", 422,
                       "Yard access profile must be VERIFIED")
    plan = svc.plans.get(sub["plan_id"])
    if plan is None or plan["plan_status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_RETIRED", 422,
                       "SubscriptionPlan is not ACTIVE")
    _check_scope(plan, yard)
    sub["status"] = "ACTIVE"
    sub["started_on"] = now()
    sub["next_billing_anchor_date"] = svc.first_of_next_month(now())
    sub["monthly_fee_cents_snapshot"] = svc.monthly_fee(plan, yard)
    svc.bump(sub)
    svc.generate_visits(sub)
    return ok_object(svc.ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/pause")
def pause_subscription(sid):
    uid, _ = auth("Customer")
    sub = _owned_subscription(sid, uid)
    if sub["status"] != "ACTIVE":
        raise err_invalid_state("pause is only valid from ACTIVE")
    customer = svc.customers.get(sub["customer_id"])
    _check_account_active(customer)
    for v in svc.visits.values():
        if v["subscription_id"] == sub["id"] and v["status"] in ("EN_ROUTE", "ON_SITE"):
            raise ApiError("ERR_VISIT_IN_FLIGHT", 409,
                           "A visit is currently EN_ROUTE or ON_SITE")
    today = now().date()
    for v in list(svc.visits.values()):
        if (
            v["subscription_id"] == sub["id"]
            and v["status"] == "SCHEDULED"
            and v["scheduled_date"].date() > today
        ):
            svc.cancel_visit_record(v, skip_source="CUSTOMER_REQUEST")
    sub["status"] = "PAUSED"
    svc.bump(sub)
    return ok_object(svc.ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/resume")
def resume_subscription(sid):
    uid, _ = auth("Customer")
    sub = _owned_subscription(sid, uid)
    if sub["status"] != "PAUSED":
        raise err_invalid_state("resume is only valid from PAUSED")
    customer = svc.customers.get(sub["customer_id"])
    _check_account_active(customer)
    profile = svc.access_profile_of_yard(sub["yard_id"])
    if profile is None or profile["access_status"] != "VERIFIED":
        raise ApiError("ERR_ACCESS_NOT_VERIFIED", 422,
                       "Yard access profile must be VERIFIED")
    yard = svc.yards.get(sub["yard_id"])
    plan = svc.plans.get(sub["plan_id"])
    sub["status"] = "ACTIVE"
    if yard is not None and plan is not None:
        sub["monthly_fee_cents_snapshot"] = svc.monthly_fee(plan, yard)
    svc.bump(sub)
    svc.generate_visits(sub)
    return ok_object(svc.ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/cancel")
def cancel_subscription(sid):
    uid, _ = auth("Customer")
    sub = _owned_subscription(sid, uid)
    if sub["status"] not in ("ACTIVE", "PAUSED"):
        raise err_invalid_state("cancel is only valid from ACTIVE or PAUSED")
    customer = svc.customers.get(sub["customer_id"])
    _check_account_active(customer)
    for v in list(svc.visits.values()):
        if (
            v["subscription_id"] == sub["id"]
            and v["status"] not in svc.TERMINAL_VISIT_STATES
        ):
            svc.cancel_visit_record(v, skip_source="CUSTOMER_REQUEST")
    sub["pending_plan_change_id"] = None
    sub["plan_change_effective_date"] = None
    sub["status"] = "CANCELLED"
    svc.bump(sub)
    return ok_object(svc.ser_subscription(sub))


@bp.post("/api/subscriptions/<sid>/plan-change")
def plan_change(sid):
    uid, _ = auth("Customer")
    data = get_body()
    new_plan_id = require(data, "new_plan_id", str)
    expected_version = require(data, "expected_subscription_version", int)
    sub = _owned_subscription(sid, uid)
    new_plan = lookup_fk(svc.plans, new_plan_id, "SubscriptionPlan")
    if sub["status"] == "CANCELLED":
        raise err_invalid_state("Cannot stage a plan change on a CANCELLED subscription")
    if expected_version != sub["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_subscription_version does not match the current version")
    yard = svc.yards.get(sub["yard_id"])
    _check_scope(new_plan, yard)
    sub["pending_plan_change_id"] = new_plan_id
    anchor = sub["next_billing_anchor_date"]
    if anchor is None:
        anchor = svc.first_of_next_month(now())
    sub["plan_change_effective_date"] = anchor
    svc.bump(sub)
    return ok_object(svc.ser_subscription(sub))
