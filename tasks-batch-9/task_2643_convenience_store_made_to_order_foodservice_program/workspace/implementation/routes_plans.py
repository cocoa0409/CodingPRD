"""Forecast-driven labor planning by daypart (PRD 3.3)."""

from flask import Blueprint

from apihttp import authenticate, created, get_body, ok, paginate, query_str
from calc import find_staffing_plan, find_store, staffing_labor_minutes
from core import DAYPARTS, base_record, db, sort_created, touch
from errors import ApiError
from serialize import staffing_plan_out

bp = Blueprint("plans", __name__)


@bp.post("/stores/<store_id>/staffing-plans")
def create_staffing_plan(store_id):
    authenticate(("StoreManager",))
    body = get_body()
    service_date = body.date("service_date")
    daypart = body.enum("daypart", DAYPARTS)
    forecast_txn_count = body.integer("forecast_txn_count", minimum=0)
    mto_share_bp = body.integer("mto_share_bp", minimum=0, maximum=10000)
    expected_store_version = body.integer("expected_store_version")
    store = find_store(store_id)
    if expected_store_version != store["version"]:
        raise ApiError("ERR_STALE_STORE_VERSION")
    incumbents = [
        p for p in db.staffing_plans.values()
        if p["store_id"] == store["id"]
        and p["service_date"] == service_date
        and p["daypart"] == daypart
    ]
    if any(p["status"] == "LOCKED" for p in incumbents):
        raise ApiError("ERR_PLAN_LOCKED")
    planned_labor_minutes, peak_multiplier_bp = staffing_labor_minutes(
        forecast_txn_count, mto_share_bp, daypart
    )
    for plan in sort_created(incumbents):
        if plan["status"] in ("DRAFT", "PUBLISHED"):
            plan["status"] = "SUPERSEDED"
            touch(plan)
    rec = base_record()
    rec.update({
        "store_id": store["id"],
        "service_date": service_date,
        "daypart": daypart,
        "forecast_txn_count": forecast_txn_count,
        "mto_share_bp": mto_share_bp,
        "planned_labor_minutes": planned_labor_minutes,
        "peak_multiplier_bp": peak_multiplier_bp,
        "status": "DRAFT",
    })
    db.staffing_plans[rec["id"]] = rec
    touch(store)
    return created(staffing_plan_out(rec))


@bp.get("/stores/<store_id>/staffing-plans")
def list_staffing_plans(store_id):
    authenticate(("ChainAdmin", "StoreManager"))
    store = find_store(store_id)
    plans = [p for p in db.staffing_plans.values() if p["store_id"] == store["id"]]
    daypart = query_str("daypart")
    service_date = query_str("service_date")
    status = query_str("status")
    if daypart is not None:
        plans = [p for p in plans if p["daypart"] == daypart]
    if service_date is not None:
        plans = [p for p in plans if p["service_date"] == service_date]
    if status is not None:
        plans = [p for p in plans if p["status"] == status]
    return paginate(sort_created(plans), staffing_plan_out)


@bp.post("/staffing-plans/<plan_id>/publish")
def publish_staffing_plan(plan_id):
    authenticate(("StoreManager",))
    plan = find_staffing_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return ok(staffing_plan_out(plan))


@bp.post("/staffing-plans/<plan_id>/lock")
def lock_staffing_plan(plan_id):
    authenticate(("StoreManager",))
    plan = find_staffing_plan(plan_id)
    if plan["status"] != "PUBLISHED":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    plan["status"] = "LOCKED"
    touch(plan)
    return ok(staffing_plan_out(plan))
