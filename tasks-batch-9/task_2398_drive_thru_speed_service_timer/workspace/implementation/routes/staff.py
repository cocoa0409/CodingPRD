"""Roster endpoints."""

from flask import Blueprint

from constants import ALL_ROLES, STAFF_STATES
from db import base_row, db
from middleware import authenticate, get_restaurant, get_staff, require_not_frozen, scope
from response import ok
from routes.helpers import list_rows
from serialize import staff_member as staff_json
from validation import body_or_400, opt_bool, opt_int, q_enum, q_str, raw_body, req_str

bp = Blueprint("staff", __name__)


@bp.route("/staff-members", methods=["POST"])
def create_staff():
    actor = authenticate(("Operator",))
    scope(actor, raw_body().get("restaurant_id"))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    full_name = req_str(body, "full_name")
    oot_certified = opt_bool(body, "oot_certified", False)
    window_certified = opt_bool(body, "window_certified", False)
    max_minutes = opt_int(body, "max_consecutive_deployment_minutes",
                          minimum=15, maximum=240, default=90)

    restaurant = get_restaurant(restaurant_id)
    require_not_frozen(restaurant)

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "full_name": full_name,
        "oot_certified": oot_certified,
        "window_certified": window_certified,
        "max_consecutive_deployment_minutes": max_minutes,
        "deployed_minutes_today": 0,
        "staff_state": "AVAILABLE",
    })
    db.staff_members[row["id"]] = row
    return ok(staff_json(row), 201)


@bp.route("/staff-members", methods=["GET"])
def list_staff():
    authenticate(ALL_ROLES)
    return list_rows(db.staff_members, staff_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("staff_state", q_enum("staff_state", STAFF_STATES)),
    ))


@bp.route("/staff-members/<staff_id>", methods=["GET"])
def read_staff(staff_id):
    authenticate(ALL_ROLES)
    return ok(staff_json(get_staff(staff_id)))
