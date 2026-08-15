"""MealPlan endpoints: nested create (OCC + draft supersede), order, fulfill, cancel."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_EVENT_NOT_FOUND,
    ERR_MEAL_PLAN_NOT_FOUND,
    ERR_STALE_EVENT_VERSION,
    ERR_INVALID_MEAL_PLAN_TRANSITION,
    ERR_EVENT_STATE_FORBIDS_WRITE,
    ERR_MEAL_ORDER_DEADLINE_PASSED,
    ERR_NO_MEAL_HEADCOUNT,
    ERR_VENDOR_CAPACITY_EXCEEDED,
    ERR_ACTIVE_MEAL_PLAN_EXISTS,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.core import mint, bump, refresh_event, ser_meal_plan, sort_entities
from validate import req_string, req_int, opt_int, check_range

bp = Blueprint("meals", __name__)

LC = ["LogisticsCoordinator"]
ORDER_DEADLINE = timedelta(hours=72)


def load_plan(plan_id):
    m = db.meal_plans.get(plan_id)
    if m is None:
        raise_err(ERR_MEAL_PLAN_NOT_FOUND, "meal plan not found")
    return m


@bp.post("/service-events/<eventId>/meal-plans")
def create_meal_plan(eventId):
    authenticate(LC)
    ev = db.events.get(eventId)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    data = body()
    vendor_name = req_string(data, "vendor_name")
    per_person = req_int(data, "per_person_cost_cents")
    surcharge = opt_int(data, "dietary_surcharge_cents", 0)
    expected = req_int(data, "expected_event_version")
    # OCC (state, step 6)
    if expected != ev["version"]:
        raise_err(ERR_STALE_EVENT_VERSION, "expected_event_version does not match current version")
    # capacity/uniqueness + range (step 11)
    check_range(per_person >= 1, "per_person_cost_cents must be >= 1")
    check_range(surcharge >= 0, "dietary_surcharge_cents must be >= 0")
    for m in db.meal_plans.values():
        if m["event_id"] == ev["id"] and m["status"] in ("ORDERED", "FULFILLED"):
            raise_err(ERR_ACTIVE_MEAL_PLAN_EXISTS, "an ordered/fulfilled meal plan already exists for this event")
    # supersede an existing DRAFT plan
    for m in sort_entities([m for m in db.meal_plans.values() if m["event_id"] == ev["id"]]):
        if m["status"] == "DRAFT":
            m["status"] = "CANCELLED"
            bump(m)
    plan = mint()
    plan.update(
        {
            "event_id": ev["id"],
            "vendor_name": vendor_name,
            "per_person_cost_cents": per_person,
            "dietary_surcharge_cents": surcharge,
            "status": "DRAFT",
            "ordered_headcount": None,
            "dietary_headcount": None,
            "total_cost_cents": None,
        }
    )
    db.meal_plans[plan["id"]] = plan
    # creating a meal plan increments the event's version by 1
    bump(ev)
    return success_object(ser_meal_plan(plan), 201)


@bp.get("/meal-plans")
def list_meal_plans():
    authenticate(["Any"])
    items = list(db.meal_plans.values())
    for param in ("event_id", "vendor_name", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [m for m in items if str(m.get(param)) == val]
    return success_list([ser_meal_plan(m) for m in sort_entities(items)])


@bp.get("/meal-plans/<mealPlanId>")
def get_meal_plan(mealPlanId):
    authenticate(["Any"])
    return success_object(ser_meal_plan(load_plan(mealPlanId)))


@bp.post("/meal-plans/<mealPlanId>/order")
def order_meal_plan(mealPlanId):
    authenticate(LC)
    plan = load_plan(mealPlanId)
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_MEAL_PLAN_TRANSITION, "only a DRAFT meal plan can be ordered")
    ev = db.events.get(plan["event_id"])
    if ev is None or db.now() > ev["_start"] - ORDER_DEADLINE:
        raise_err(ERR_MEAL_ORDER_DEADLINE_PASSED, "the 72-hour meal order deadline has passed")
    ordered, dietary = calc.meal_snapshot(ev, plan)
    if ordered < 1:
        raise_err(ERR_NO_MEAL_HEADCOUNT, "no confirmed diners want a meal")
    pool = calc.vendor_day_pool(plan["vendor_name"], ev["_start"].date(), exclude_id=plan["id"])
    if pool + ordered > calc.VENDOR_DAILY_CAPACITY:
        raise_err(ERR_VENDOR_CAPACITY_EXCEEDED, "vendor daily capacity would be exceeded")
    plan["ordered_headcount"] = ordered
    plan["dietary_headcount"] = dietary
    plan["total_cost_cents"] = (ordered - dietary) * plan["per_person_cost_cents"] + dietary * (
        plan["per_person_cost_cents"] + plan["dietary_surcharge_cents"]
    )
    plan["status"] = "ORDERED"
    bump(plan)
    refresh_event(ev)
    return success_object(ser_meal_plan(plan))


@bp.post("/meal-plans/<mealPlanId>/fulfill")
def fulfill_meal_plan(mealPlanId):
    authenticate(LC)
    plan = load_plan(mealPlanId)
    if plan["status"] != "ORDERED":
        raise_err(ERR_INVALID_MEAL_PLAN_TRANSITION, "only an ORDERED meal plan can be fulfilled")
    ev = db.events.get(plan["event_id"])
    if ev is None or ev["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event must be IN_PROGRESS or COMPLETED")
    plan["status"] = "FULFILLED"
    bump(plan)
    refresh_event(ev)
    return success_object(ser_meal_plan(plan))


@bp.post("/meal-plans/<mealPlanId>/cancel")
def cancel_meal_plan(mealPlanId):
    authenticate(LC)
    plan = load_plan(mealPlanId)
    if plan["status"] not in ("DRAFT", "ORDERED"):
        raise_err(ERR_INVALID_MEAL_PLAN_TRANSITION, "meal plan cannot be cancelled from its current status")
    plan["status"] = "CANCELLED"
    bump(plan)
    ev = db.events.get(plan["event_id"])
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_meal_plan(plan))
