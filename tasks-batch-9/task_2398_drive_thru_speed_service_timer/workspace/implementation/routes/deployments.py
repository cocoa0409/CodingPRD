"""Order-taker deployments and the labor-minutes ledger."""

from flask import Blueprint

from constants import ALL_ROLES, CHANGEOVER_BUFFER_SECONDS, DEPLOYMENT_STATES, OOT_POSITIONS, POSITIONS
from db import base_row, db, seconds_between, touch
from errors import fail
from middleware import (
    authenticate,
    get_deployment,
    get_profile,
    get_restaurant,
    get_staff,
    require_not_frozen,
    scope,
)
from response import ok
from routes.helpers import list_rows
from serialize import deployment as deployment_json
from services.rollup import recompute
from validation import body_or_400, q_enum, q_str, raw_body, req_dt, req_enum, req_str

bp = Blueprint("deployments", __name__)


def _ceil_minutes(seconds):
    return -(-seconds // 60)


@bp.route("/order-taker-deployments", methods=["POST"])
def create_deployment():
    actor = authenticate(("Operator",))
    scope(actor, raw_body().get("restaurant_id"))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    staff_member_id = req_str(body, "staff_member_id")
    daypart_profile_id = req_str(body, "daypart_profile_id")
    position = req_enum(body, "position", POSITIONS)
    planned_start_at = req_dt(body, "planned_start_at")
    planned_end_at = req_dt(body, "planned_end_at")

    restaurant = get_restaurant(restaurant_id)
    staff = get_staff(staff_member_id)
    profile = get_profile(daypart_profile_id)

    if staff["restaurant_id"] != restaurant_id:
        fail("ERR_RESTAURANT_MISMATCH", "the team member belongs to another store")
    if profile["restaurant_id"] != restaurant_id:
        fail("ERR_RESTAURANT_MISMATCH", "the daypart profile belongs to another store")

    require_not_frozen(restaurant)

    if position in OOT_POSITIONS and not staff["oot_certified"]:
        fail("ERR_STAFF_NOT_OOT_CERTIFIED",
             "an outside order-taker position requires oot_certified")

    if planned_end_at <= planned_start_at:
        fail("ERR_WINDOW_BOUNDS_INVALID", "planned_end_at must be after planned_start_at")

    for row in db.deployments.values():
        if row["staff_member_id"] != staff_member_id:
            continue
        if row["deployment_state"] not in ("PLANNED", "ACTIVE"):
            continue
        after = seconds_between(planned_start_at, row["planned_end_at"]) >= CHANGEOVER_BUFFER_SECONDS
        before = seconds_between(row["planned_start_at"], planned_end_at) >= CHANGEOVER_BUFFER_SECONDS
        if not (after or before):
            fail("ERR_DEPLOYMENT_BUFFER_VIOLATION",
                 "deployments of one team member need a 600-second changeover buffer")

    planned_minutes = _ceil_minutes(seconds_between(planned_end_at, planned_start_at))
    if planned_minutes > staff["max_consecutive_deployment_minutes"]:
        fail("ERR_STAFF_CONSECUTIVE_LIMIT",
             "planned_minutes exceeds max_consecutive_deployment_minutes")

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "staff_member_id": staff_member_id,
        "daypart_profile_id": daypart_profile_id,
        "position": position,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
        "planned_minutes": planned_minutes,
        "activated_at": None,
        "released_at": None,
        "labor_minutes_charged": 0,
        "deployment_state": "PLANNED",
        "abort_reason": None,
    })
    db.deployments[row["id"]] = row
    return ok(deployment_json(row), 201)


@bp.route("/order-taker-deployments/<deployment_id>/activate", methods=["POST"])
def activate_deployment(deployment_id):
    actor = authenticate(("Operator", "ShiftLeader"))
    deployment = get_deployment(deployment_id)
    scope(actor, deployment["restaurant_id"])
    restaurant = db.restaurants.get(deployment["restaurant_id"])
    require_not_frozen(restaurant)

    if deployment["deployment_state"] != "PLANNED":
        fail("ERR_INVALID_DEPLOYMENT_STATE",
             "activation requires deployment_state PLANNED, found %s"
             % deployment["deployment_state"])

    staff = db.staff_members.get(deployment["staff_member_id"])
    if staff is None or staff["staff_state"] != "AVAILABLE":
        fail("ERR_STAFF_NOT_AVAILABLE", "the team member is not AVAILABLE")

    if restaurant["labor_minutes_available"] < deployment["planned_minutes"]:
        fail("ERR_LABOR_BUDGET_EXCEEDED",
             "the store has %s labor minutes available" % restaurant["labor_minutes_available"])

    deployment["deployment_state"] = "ACTIVE"
    deployment["activated_at"] = db.clock
    touch(deployment)

    staff["staff_state"] = "DEPLOYED"
    touch(staff)

    recompute(restaurant)
    return ok(deployment_json(deployment))


@bp.route("/order-taker-deployments/<deployment_id>/release", methods=["POST"])
def release_deployment(deployment_id):
    actor = authenticate(("Operator", "ShiftLeader"))
    deployment = get_deployment(deployment_id)
    scope(actor, deployment["restaurant_id"])
    restaurant = db.restaurants.get(deployment["restaurant_id"])
    require_not_frozen(restaurant)

    if deployment["deployment_state"] != "ACTIVE":
        fail("ERR_INVALID_DEPLOYMENT_STATE",
             "release requires deployment_state ACTIVE, found %s"
             % deployment["deployment_state"])

    released_at = db.clock
    elapsed = _ceil_minutes(seconds_between(released_at, deployment["activated_at"]))
    charged = min(deployment["planned_minutes"], elapsed)

    deployment["deployment_state"] = "RELEASED"
    deployment["released_at"] = released_at
    deployment["labor_minutes_charged"] = charged
    touch(deployment)

    staff = db.staff_members.get(deployment["staff_member_id"])
    if staff is not None:
        staff["staff_state"] = "AVAILABLE"
        staff["deployed_minutes_today"] = staff["deployed_minutes_today"] + charged
        touch(staff)

    recompute(restaurant)
    return ok(deployment_json(deployment))


@bp.route("/order-taker-deployments/<deployment_id>/abort", methods=["POST"])
def abort_deployment(deployment_id):
    actor = authenticate(("Operator",))
    deployment = get_deployment(deployment_id)
    scope(actor, deployment["restaurant_id"])
    body = body_or_400()
    reason = req_str(body, "abort_reason")

    restaurant = db.restaurants.get(deployment["restaurant_id"])
    require_not_frozen(restaurant)

    if deployment["deployment_state"] not in ("PLANNED", "ACTIVE"):
        fail("ERR_INVALID_DEPLOYMENT_STATE",
             "abort requires deployment_state PLANNED or ACTIVE, found %s"
             % deployment["deployment_state"])

    was_active = deployment["deployment_state"] == "ACTIVE"
    deployment["deployment_state"] = "ABORTED"
    deployment["abort_reason"] = reason
    touch(deployment)

    if was_active:
        staff = db.staff_members.get(deployment["staff_member_id"])
        if staff is not None:
            staff["staff_state"] = "AVAILABLE"
            touch(staff)

    recompute(restaurant)
    return ok(deployment_json(deployment))


@bp.route("/order-taker-deployments", methods=["GET"])
def list_deployments():
    authenticate(ALL_ROLES)
    return list_rows(db.deployments, deployment_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("staff_member_id", q_str("staff_member_id")),
        ("daypart_profile_id", q_str("daypart_profile_id")),
        ("position", q_enum("position", POSITIONS)),
        ("deployment_state", q_enum("deployment_state", DEPLOYMENT_STATES)),
    ))


@bp.route("/order-taker-deployments/<deployment_id>", methods=["GET"])
def read_deployment(deployment_id):
    authenticate(ALL_ROLES)
    return ok(deployment_json(get_deployment(deployment_id)))
