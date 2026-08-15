"""DeliveryComplaint and CreditMemo endpoints (subscriber-care surface)."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_complaint, ser_credit_memo
from util import days, rhu
from validate import opt_int, req_date, req_enum, req_int, req_str
from decimal import Decimal

bp = Blueprint("service", __name__)

COMPLAINT_TYPES = ("MISSED", "DAMAGED", "LATE", "OTHER")


# --- DeliveryComplaint ------------------------------------------------------

@bp.post("/api/complaints")
def create_complaint():
    uid, role = require_roles("Subscriber", "ServiceRep", "CirculationDirector")
    b = body()
    subscription_id = req_str(b, "subscription_id")
    service_date = req_date(b, "service_date")
    complaint_type = req_enum(b, "complaint_type", COMPLAINT_TYPES)
    if service_date > domain.today():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "service_date must not be in the future")
    sub = domain.fetch(store.subscriptions, subscription_id)
    own_check(uid, role, sub["subscriber_id"])
    # State: subscription must be in an active billing state.
    if sub["billing_status"] not in domain.ACTIVE_SET:
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Complaint requires billing_status ACTIVE or GRACE")
    # Temporal: filing window is [today-7, today].
    if service_date < domain.today() - days(7):
        raise ApiError("ERR_COMPLAINT_WINDOW_CLOSED", 409,
                       "service_date is older than 7 days before today")
    # Referential: print-capable plans only.
    plan = domain.plan_of(sub)
    if not domain.print_capable(plan):
        raise ApiError("ERR_DIGITAL_ONLY_PLAN", 409,
                       "Complaints require a print-capable plan")
    # Uniqueness: one non-DENIED complaint per (subscription, service_date).
    for c in store.complaints.values():
        if c["subscription_id"] == sub["id"] and c["service_date"] == service_date \
                and c["status"] != "DENIED":
            raise ApiError("ERR_DUPLICATE_COMPLAINT", 409,
                           "A non-DENIED complaint already exists for this service_date")
    rec = create_rec(store.complaints, {
        "subscription_id": sub["id"],
        "service_date": service_date,
        "complaint_type": complaint_type,
        "route_id": domain.resolve_route_id(sub, service_date),
        "status": "OPEN",
        "credit_amount_cents": None,
        "deny_reason": None,
    })
    return ok_obj(ser_complaint(rec), 201)


@bp.get("/api/complaints")
def list_complaints():
    require_roles("ServiceRep", "DistrictManager", "CirculationDirector")
    recs = by_created(store.complaints.values())
    subscription_id = request.args.get("subscription_id")
    if subscription_id is not None:
        recs = [c for c in recs if c["subscription_id"] == subscription_id]
    route_id = request.args.get("route_id")
    if route_id is not None:
        recs = [c for c in recs if c["route_id"] == route_id]
    status = request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_complaint)


@bp.get("/api/complaints/<cid>")
def get_complaint(cid):
    uid, role = require_roles("Subscriber", "ServiceRep", "DistrictManager",
                              "CirculationDirector")
    complaint = domain.fetch(store.complaints, cid)
    sub = store.subscriptions.get(complaint["subscription_id"])
    own_check(uid, role, sub["subscriber_id"] if sub else None)
    return ok_obj(ser_complaint(complaint))


@bp.post("/api/complaints/<cid>/credit")
def credit_complaint(cid):
    require_roles("ServiceRep", "CirculationDirector")
    complaint = domain.fetch(store.complaints, cid)
    b = body()
    amount = opt_int(b, "amount_cents", min_v=1)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_NOT_OPEN", 409,
                       "Complaint credit requires status OPEN")
    sub = store.subscriptions[complaint["subscription_id"]]
    plan = domain.plan_of(sub)
    if amount is None:
        # Default: current effective weekly rate / issues_per_week, half-up.
        rate = domain.effective_weekly_rate(sub, plan, domain.today())
        amount = rhu(Decimal(rate) / Decimal(plan["issues_per_week"]))
    # Money checks last: per-complaint cap, then monthly goodwill cap.
    if amount > domain.COMPLAINT_CREDIT_CAP_CENTS:
        raise ApiError("ERR_CREDIT_EXCEEDS_COMPLAINT_CAP", 409,
                       "Complaint credit exceeds the 2000-cent cap")
    used = domain.monthly_goodwill_used(sub["subscriber_id"])
    if used + amount > domain.MONTHLY_GOODWILL_CAP_CENTS:
        raise ApiError("ERR_GOODWILL_CAP_EXCEEDED", 409,
                       "Monthly goodwill cap would be exceeded")
    complaint["status"] = "CREDITED"
    complaint["credit_amount_cents"] = amount
    bump(complaint)
    memo = create_rec(store.credit_memos, {
        "subscriber_id": sub["subscriber_id"],
        "source": "COMPLAINT",
        "complaint_id": complaint["id"],
        "hold_id": None,
        "amount_cents": amount,
        "applied_cents": 0,
        "reason": f"Complaint credit ({complaint['complaint_type']})",
        "status": "ISSUED",
    })
    domain.auto_apply_credit(memo)
    return ok_obj(ser_credit_memo(memo))


@bp.post("/api/complaints/<cid>/deny")
def deny_complaint(cid):
    require_roles("ServiceRep", "CirculationDirector")
    complaint = domain.fetch(store.complaints, cid)
    b = body()
    reason = req_str(b, "reason")
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_COMPLAINT_NOT_OPEN", 409,
                       "Complaint deny requires status OPEN")
    complaint["status"] = "DENIED"
    complaint["deny_reason"] = reason
    bump(complaint)
    return ok_obj(ser_complaint(complaint))


# --- CreditMemo -------------------------------------------------------------

@bp.post("/api/credit-memos")
def create_credit_memo():
    require_roles("ServiceRep", "CirculationDirector")
    b = body()
    subscriber_id = req_str(b, "subscriber_id")
    amount = req_int(b, "amount_cents", min_v=1)
    reason = req_str(b, "reason")
    subr = domain.fetch(store.subscribers, subscriber_id)
    used = domain.monthly_goodwill_used(subr["id"])
    if used + amount > domain.MONTHLY_GOODWILL_CAP_CENTS:
        raise ApiError("ERR_GOODWILL_CAP_EXCEEDED", 409,
                       "Monthly goodwill cap would be exceeded")
    memo = create_rec(store.credit_memos, {
        "subscriber_id": subr["id"],
        "source": "GOODWILL",
        "complaint_id": None,
        "hold_id": None,
        "amount_cents": amount,
        "applied_cents": 0,
        "reason": reason,
        "status": "ISSUED",
    })
    domain.auto_apply_credit(memo)
    return ok_obj(ser_credit_memo(memo), 201)


@bp.get("/api/credit-memos")
def list_credit_memos():
    require_roles("ServiceRep", "CirculationDirector")
    recs = by_created(store.credit_memos.values())
    for param in ("subscriber_id", "complaint_id", "hold_id", "source", "status"):
        v = request.args.get(param)
        if v is not None:
            recs = [m for m in recs if m[param] == v]
    return paginate(recs, ser_credit_memo)


@bp.get("/api/credit-memos/<mid>")
def get_credit_memo(mid):
    require_roles("ServiceRep", "CirculationDirector")
    return ok_obj(ser_credit_memo(domain.fetch(store.credit_memos, mid)))


@bp.post("/api/credit-memos/<mid>/void")
def void_credit_memo(mid):
    require_roles("CirculationDirector")
    memo = domain.fetch(store.credit_memos, mid)
    if memo["status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Credit memo already VOIDED")
    if memo["applied_cents"] != 0:
        raise ApiError("ERR_CREDIT_MEMO_LOCKED", 409,
                       "Void requires applied_cents == 0")
    memo["status"] = "VOIDED"
    bump(memo)
    return ok_obj(ser_credit_memo(memo))
