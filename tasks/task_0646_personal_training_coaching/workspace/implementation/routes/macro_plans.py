"""MacroPlan endpoints + lifecycle (PRD §3.7)."""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from clock import clock
from helpers import (get_json_body, require_fields, require_enum,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import macro_plan_view
from services import domain
from services import calculations as calc

bp = Blueprint("macro_plans", __name__)

GOALS = {"FAT_LOSS", "MAINTENANCE", "MUSCLE_GAIN"}
ACTIVITY_LEVELS = {"SEDENTARY", "MODERATE", "ACTIVE"}


@bp.route("/engagements/<engagement_id>/macro-plans", methods=["POST"])
@require_roles("Trainer")
def create_macro_plan(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)

    body = get_json_body()
    require_fields(body, "goal", "activity_level")
    goal = require_enum(body["goal"], GOALS, "goal")
    activity_level = require_enum(body["activity_level"], ACTIVITY_LEVELS, "activity_level")

    client = db.clients.get(engagement["client_id"])

    # ERR_NO_WEIGHT_FOR_MACROS: weight null OR a macro plan already exists.
    existing = any(
        m["engagement_id"] == engagement_id and m["status"] in ("PROVISIONAL", "LOCKED")
        for m in db.macro_plans.values()
    )
    if client["latest_weight_kg"] is None or existing:
        raise errors.invalid_state(errors.ERR_NO_WEIGHT_FOR_MACROS,
                                   "No weight available or a macro plan already exists")

    weight = client["latest_weight_kg"]
    age = clock.now().year - client["birth_year"]
    tc, p, cb, f = calc.macro_targets(
        client["sex"], client["height_cm"], age, weight, goal, activity_level)

    mid = new_id()
    ts = now_ts()
    plan = {
        "id": mid,
        "engagement_id": engagement_id,
        "goal": goal,
        "activity_level": activity_level,
        "snapshot_weight_kg": weight,
        "target_calories": tc,
        "protein_g": p,
        "carb_g": cb,
        "fat_g": f,
        "status": "PROVISIONAL",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.macro_plans[mid] = plan
    return success(macro_plan_view(plan), 201)


@bp.route("/macro-plans/<macro_plan_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_macro_plan(macro_plan_id):
    plan = domain.get_macro_plan(macro_plan_id)
    engagement = domain.get_engagement(plan["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(macro_plan_view(plan), 200)


@bp.route("/engagements/<engagement_id>/macro-plans", methods=["GET"])
@require_roles("Trainer", "Client")
def list_macro_plans(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    limit, offset = pagination_params()
    items = [m for m in db.macro_plans.values() if m["engagement_id"] == engagement_id]
    items.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([macro_plan_view(m) for m in page], limit, offset, total, 200)


@bp.route("/macro-plans/<macro_plan_id>/lock", methods=["POST"])
@require_roles("Trainer")
def lock_macro_plan(macro_plan_id):
    plan = domain.get_macro_plan(macro_plan_id)
    engagement = domain.get_engagement(plan["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if plan["status"] != "PROVISIONAL":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Macro plan is not PROVISIONAL")
    plan["status"] = "LOCKED"
    domain.touch(plan)
    return success(macro_plan_view(plan), 200)
