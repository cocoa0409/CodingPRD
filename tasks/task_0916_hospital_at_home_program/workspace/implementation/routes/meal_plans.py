"""Meal plans and care coordination (PRD 3.7)."""

from flask import Blueprint

import calc
import clock
import envelope
import errors
import ladder
import serializers
import store
from errors import fail
from routes.common import apply_filter, endpoint
from routes.patients import DIET_CODES
from store import DB

bp = Blueprint("meal_plans", __name__)

MEAL_LIST_ROLES = [
    "ProgramAdmin", "AdmittingPhysician", "LogisticsCoordinator", "BillingAnalyst",
]


@endpoint(bp, "/meal-plans", ["POST"], ["LogisticsCoordinator"])
def create_meal_plan(caller):
    body = ladder.json_body()
    # rung 4a
    ladder.require_fields(body, ["episode_id", "diet_code", "daily_delivery_count"])
    # rung 4b
    ladder.check_enum(body, "diet_code", DIET_CODES)
    # rung 4c
    ladder.check_integer_range(
        body, "daily_delivery_count",
        calc.MEAL_MIN_DAILY_DELIVERIES, calc.MEAL_MAX_DAILY_DELIVERIES,
    )
    # rung 5
    episode = ladder.body_episode(body)
    # rung 8
    ladder.require_episode_active(episode)
    # rung 13 -- the diet compatibility rule is deliberately asymmetric
    patient = DB.patients.get(episode["patient_id"])
    restriction = patient["diet_restriction"] if patient else "NONE"
    if restriction != "NONE" and body["diet_code"] != restriction:
        fail(errors.ERR_DIET_INCOMPATIBLE)

    plan = store.make_row("meal_plans", {
        "episode_id": episode["id"],
        "diet_code": body["diet_code"],
        "daily_delivery_count": body["daily_delivery_count"],
        "activated_on_date": clock.today_date(),
        "status": "ACTIVE",
        "suspension_day_count": 0,
    })
    return envelope.ObjResult(plan, serializers.meal_plan, 201)


@endpoint(bp, "/episodes/<episode_id>/meal-plans", ["GET"], MEAL_LIST_ROLES)
def list_meal_plans(caller, episode_id):
    # rung 3
    ladder.path_row("episodes", episode_id)
    limit, offset = ladder.pagination_params()
    rows = [p for p in DB.meal_plans.values() if p["episode_id"] == episode_id]
    rows = apply_filter(rows, "status")
    return envelope.ListResult(store.ordered(rows), serializers.meal_plan, limit, offset)
