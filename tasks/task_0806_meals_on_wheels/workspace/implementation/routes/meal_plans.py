from flask import Blueprint

import db
import core
import ser
import find
import cascade
from core import ApiError

bp = Blueprint("meal_plans", __name__)

MEAL_TYPES = {"FROZEN", "HOT", "THERAPEUTIC"}
DIET_TYPES = {"NONE", "RENAL", "DIABETIC", "LOW_SODIUM", "PUREED"}


@bp.post("/clients/<cid>/meal-plans")
@core.require_auth(["RouteManager"])
def create_meal_plan(cid):
    body = core.get_body()
    assessment_id = core.require_field(body, "assessment_id", "str")
    route_id = core.require_field(body, "route_id", "str")
    meal_type = core.require_field(body, "meal_type", "str")
    meals_per_day = core.require_field(body, "meals_per_day", "int")
    delivery_days = core.require_field(body, "delivery_days", "list")
    expected = core.require_field(body, "expected_client_version", "int")
    diet_type = core.optional_field(body, "therapeutic_diet_type", "str", default="NONE")

    # field-value validation
    core.check_enum(meal_type, MEAL_TYPES, "invalid meal_type")
    core.check_enum(diet_type, DIET_TYPES, "invalid therapeutic_diet_type")
    if not (1 <= meals_per_day <= 3):
        core.invalid_value("meals_per_day must be 1..3")
    if len(delivery_days) == 0:
        core.invalid_value("delivery_days must be non-empty")
    for day in delivery_days:
        if day not in core.WEEKDAY_SET:
            core.invalid_value("delivery_days contains an invalid weekday")

    # path existence
    client = find.client(cid)
    # body FK existence
    assessment = find.assessment(assessment_id)
    route = find.route(route_id)

    # referential consistency
    if assessment["client_id"] != cid:
        raise ApiError("ERR_ASSESSMENT_CLIENT_MISMATCH", 422, "assessment does not belong to this client")

    # state preconditions
    if assessment["status"] != "FINALIZED":
        raise ApiError("ERR_ASSESSMENT_NOT_FINALIZED", 409, "assessment must be FINALIZED")
    if route["status"] != "ACTIVE":
        raise ApiError("ERR_ROUTE_NOT_ACTIVE", 409, "route must be ACTIVE")
    if client["enrollment_status"] not in ("ASSESSED", "ACTIVE"):
        raise ApiError("ERR_CLIENT_NOT_ASSESSED", 409, "client must be ASSESSED or ACTIVE")

    # domain safety: therapeutic diet matching
    if meal_type == "THERAPEUTIC":
        if not assessment["therapeutic_diet_required"] or assessment["therapeutic_diet_type"] != diet_type:
            raise ApiError("ERR_THERAPEUTIC_DIET_MISMATCH", 422, "therapeutic diet does not match assessment")

    # business constraint: zone matching
    if route["zone"] != client["address_zone"]:
        raise ApiError("ERR_ROUTE_ZONE_MISMATCH", 422, "route zone does not match client address zone")

    # optimistic concurrency (last)
    if expected != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION", 412, "expected_client_version does not match")

    # --- side effects: supersede prior ACTIVE plan ---
    prior = ser.active_meal_plan(cid)
    if prior is not None:
        prior["status"] = "CANCELLED"
        db.touch(prior)
        cascade.cancel_scheduled_deliveries_of_plan(prior["id"])

    n_days = len(delivery_days)
    weekly = core.compute_weekly_meal_count(meal_type, meals_per_day, n_days)
    per_meal = core.per_meal_contribution_cents(client["income_tier"])

    rec = db.base_record()
    rec.update({
        "client_id": cid,
        "assessment_id": assessment_id,
        "route_id": route_id,
        "meal_type": meal_type,
        "therapeutic_diet_type": diet_type,
        "meals_per_day": meals_per_day,
        "delivery_days": delivery_days,
        "weekly_meal_count": weekly,
        "suggested_contribution_per_meal_cents": per_meal,
        "status": "ACTIVE",
    })
    db.meal_plans[rec["id"]] = rec

    db.touch(client)
    return core.ok_object(ser.meal_plan(rec), 201)


@bp.get("/meal-plans/<mid>")
@core.require_auth(core.ALL_ROLES)
def get_meal_plan(mid):
    m = find.meal_plan(mid)
    return core.ok_object(ser.meal_plan(m))


@bp.get("/meal-plans")
@core.require_auth(core.ALL_ROLES)
def list_meal_plans():
    args = core.request.args
    items = list(db.meal_plans.values())
    for key in ("client_id", "assessment_id", "route_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [m for m in items if m[key] == val]
    items = ser.sorted_by_seq(items)
    limit, offset = core.get_pagination()
    page, total = core.paginate(items, limit, offset)
    return core.ok_array([ser.meal_plan(m) for m in page], limit, offset, total)


@bp.post("/meal-plans/<mid>/cancel")
@core.require_auth(["RouteManager"])
def cancel_meal_plan(mid):
    m = find.meal_plan(mid)
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEAL_PLAN_NOT_ACTIVE", 409, "meal plan must be ACTIVE to cancel")
    m["status"] = "CANCELLED"
    db.touch(m)
    cascade.cancel_scheduled_deliveries_of_plan(mid)
    return core.ok_object(ser.meal_plan(m))
