"""SubscriptionPlan and Subscriber endpoints."""
from flask import Blueprint, request

import domain
from db import bump, by_created, create_rec, store
from errors import ApiError
from middleware import body, own_check, require_roles
from response import ok_obj, paginate
from serialize import ser_plan, ser_subscriber
from validate import opt_enum, opt_str, req_enum, req_int, req_str

bp = Blueprint("catalog", __name__)

PLAN_TYPES = ("PRINT", "DIGITAL", "BUNDLE")
PRORATION_METHODS = ("PER_DAY", "PER_ISSUE")


# --- SubscriptionPlan -------------------------------------------------------

@bp.post("/api/subscription-plans")
def create_plan():
    require_roles("CirculationDirector")
    b = body()
    name = req_str(b, "name")
    plan_type = req_enum(b, "plan_type", PLAN_TYPES)
    ipw = req_int(b, "issues_per_week")
    if plan_type == "DIGITAL":
        if ipw != 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "issues_per_week must be 0 when plan_type is DIGITAL")
    elif not (1 <= ipw <= 7):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "issues_per_week must be between 1 and 7 for print-capable plans")
    base_rate = req_int(b, "base_weekly_rate_cents", min_v=1)
    min_rate = req_int(b, "min_weekly_rate_cents", min_v=0)
    proration = opt_enum(b, "proration_method", PRORATION_METHODS, default="PER_DAY")
    sched_in = b.get("step_up_schedule")
    if sched_in is None:
        sched_in = []
    if not isinstance(sched_in, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "step_up_schedule must be an array")
    schedule = []
    for entry in sched_in:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "step_up_schedule entries must be objects")
        aw = entry.get("after_weeks")
        wr = entry.get("weekly_rate_cents")
        if not (isinstance(aw, int) and not isinstance(aw, bool)) or aw < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "step_up_schedule.after_weeks must be an integer >= 0")
        if not (isinstance(wr, int) and not isinstance(wr, bool)) or wr <= 0:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "step_up_schedule.weekly_rate_cents must be an integer > 0")
        schedule.append({"after_weeks": aw, "weekly_rate_cents": wr})
    schedule.sort(key=lambda s: s["after_weeks"])
    rec = create_rec(store.plans, {
        "name": name,
        "plan_type": plan_type,
        "issues_per_week": ipw,
        "base_weekly_rate_cents": base_rate,
        "step_up_schedule": schedule,
        "proration_method": proration,
        "min_weekly_rate_cents": min_rate,
        "status": "ACTIVE",
    })
    return ok_obj(ser_plan(rec), 201)


@bp.get("/api/subscription-plans")
def list_plans():
    require_roles("Subscriber", "ServiceRep", "DistrictManager", "CirculationDirector")
    recs = by_created(store.plans.values())
    plan_type = request.args.get("plan_type")
    if plan_type is not None:
        recs = [p for p in recs if p["plan_type"] == plan_type]
    status = request.args.get("status")
    if status is not None:
        recs = [p for p in recs if p["status"] == status]
    return paginate(recs, ser_plan)


@bp.get("/api/subscription-plans/<pid>")
def get_plan(pid):
    require_roles("Subscriber", "ServiceRep", "DistrictManager", "CirculationDirector")
    return ok_obj(ser_plan(domain.fetch(store.plans, pid)))


@bp.post("/api/subscription-plans/<pid>/retire")
def retire_plan(pid):
    require_roles("CirculationDirector")
    plan = domain.fetch(store.plans, pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Plan is not ACTIVE")
    plan["status"] = "RETIRED"
    bump(plan)
    return ok_obj(ser_plan(plan))


# --- Subscriber -------------------------------------------------------------

@bp.post("/api/subscribers")
def create_subscriber():
    require_roles("ServiceRep", "CirculationDirector")
    b = body()
    display_name = req_str(b, "display_name")
    email = req_str(b, "email")
    service_address = opt_str(b, "service_address")
    rec = create_rec(store.subscribers, {
        "display_name": display_name,
        "email": email,
        "service_address": service_address,
        "status": "ACTIVE",
        "balance_due_cents": 0,
        "unapplied_cash_cents": 0,
    })
    return ok_obj(ser_subscriber(rec), 201)


@bp.get("/api/subscribers")
def list_subscribers():
    require_roles("ServiceRep", "DistrictManager", "CirculationDirector")
    recs = by_created(store.subscribers.values())
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    return paginate(recs, ser_subscriber)


@bp.get("/api/subscribers/<sid>")
def get_subscriber(sid):
    uid, role = require_roles("Subscriber", "ServiceRep", "DistrictManager",
                              "CirculationDirector")
    own_check(uid, role, sid)  # Subscriber role: own record only
    return ok_obj(ser_subscriber(domain.fetch(store.subscribers, sid)))


@bp.post("/api/subscribers/<sid>/close")
def close_subscriber(sid):
    require_roles("ServiceRep", "CirculationDirector")
    subr = domain.fetch(store.subscribers, sid)
    if subr["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a LAPSED subscriber can be closed")
    if subr["balance_due_cents"] != 0 or subr["unapplied_cash_cents"] != 0:
        raise ApiError("ERR_SUBSCRIBER_NOT_SETTLED", 409,
                       "Subscriber ledger is not settled")
    subr["status"] = "CLOSED"
    bump(subr)
    return ok_obj(ser_subscriber(subr))
