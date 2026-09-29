"""Daypart profiles: draft, activate (with half-open overlap geometry), retire."""

from flask import Blueprint

from constants import ALL_ROLES, DAYPARTS, PROFILE_STATES
from db import base_row, db, touch
from errors import fail
from middleware import authenticate, get_profile, get_restaurant, require_not_frozen, scope
from response import ok
from routes.helpers import list_rows
from serialize import daypart_profile as profile_json
from validation import body_or_400, q_enum, q_str, raw_body, req_enum, req_int, req_str

bp = Blueprint("dayparts", __name__)


@bp.route("/daypart-profiles", methods=["POST"])
def create_profile():
    actor = authenticate(("Operator",))
    scope(actor, raw_body().get("restaurant_id"))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    daypart = req_enum(body, "daypart", DAYPARTS)
    start_minute = req_int(body, "start_minute", minimum=0, maximum=1439)
    end_minute = req_int(body, "end_minute", minimum=1, maximum=1440)
    greet = req_int(body, "greet_target_seconds", minimum=1, maximum=600)
    order = req_int(body, "order_target_seconds", minimum=1, maximum=600)
    pull_forward = req_int(body, "pull_forward_target_seconds", minimum=1, maximum=600)
    window = req_int(body, "window_target_seconds", minimum=1, maximum=600)

    restaurant = get_restaurant(restaurant_id)
    require_not_frozen(restaurant)

    if end_minute <= start_minute:
        fail("ERR_WINDOW_BOUNDS_INVALID", "end_minute must be greater than start_minute")

    for row in db.daypart_profiles.values():
        if (row["restaurant_id"] == restaurant_id and row["daypart"] == daypart
                and row["profile_state"] in ("DRAFT", "ACTIVE")):
            fail("ERR_DUPLICATE_DAYPART",
                 "this store already holds a %s profile in DRAFT or ACTIVE" % daypart)

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "daypart": daypart,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "greet_target_seconds": greet,
        "order_target_seconds": order,
        "pull_forward_target_seconds": pull_forward,
        "window_target_seconds": window,
        "total_target_seconds": greet + order + pull_forward + window,
        "profile_state": "DRAFT",
    })
    db.daypart_profiles[row["id"]] = row
    return ok(profile_json(row), 201)


@bp.route("/daypart-profiles/<profile_id>/activate", methods=["POST"])
def activate_profile(profile_id):
    actor = authenticate(("Operator",))
    profile = get_profile(profile_id)
    scope(actor, profile["restaurant_id"])
    require_not_frozen(db.restaurants.get(profile["restaurant_id"]))

    if profile["profile_state"] != "DRAFT":
        fail("ERR_INVALID_PROFILE_STATE",
             "activation requires profile_state DRAFT, found %s" % profile["profile_state"])

    for row in db.daypart_profiles.values():
        if row["id"] == profile["id"]:
            continue
        if row["restaurant_id"] != profile["restaurant_id"]:
            continue
        if row["profile_state"] != "ACTIVE":
            continue
        if profile["start_minute"] < row["end_minute"] and row["start_minute"] < profile["end_minute"]:
            fail("ERR_DAYPART_WINDOW_OVERLAP",
                 "the window overlaps an ACTIVE profile of this store")

    profile["profile_state"] = "ACTIVE"
    profile["total_target_seconds"] = (
        profile["greet_target_seconds"] + profile["order_target_seconds"]
        + profile["pull_forward_target_seconds"] + profile["window_target_seconds"]
    )
    touch(profile)
    return ok(profile_json(profile))


@bp.route("/daypart-profiles/<profile_id>/retire", methods=["POST"])
def retire_profile(profile_id):
    actor = authenticate(("Operator",))
    profile = get_profile(profile_id)
    scope(actor, profile["restaurant_id"])
    require_not_frozen(db.restaurants.get(profile["restaurant_id"]))

    if profile["profile_state"] not in ("DRAFT", "ACTIVE"):
        fail("ERR_INVALID_PROFILE_STATE",
             "retirement requires profile_state DRAFT or ACTIVE, found %s"
             % profile["profile_state"])

    profile["profile_state"] = "RETIRED"
    touch(profile)
    return ok(profile_json(profile))


@bp.route("/daypart-profiles", methods=["GET"])
def list_profiles():
    authenticate(ALL_ROLES)
    return list_rows(db.daypart_profiles, profile_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("daypart", q_enum("daypart", DAYPARTS)),
        ("profile_state", q_enum("profile_state", PROFILE_STATES)),
    ))


@bp.route("/daypart-profiles/<profile_id>", methods=["GET"])
def read_profile(profile_id):
    authenticate(ALL_ROLES)
    return ok(profile_json(get_profile(profile_id)))
