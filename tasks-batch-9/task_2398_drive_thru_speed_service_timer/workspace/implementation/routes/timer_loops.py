"""Timer loops: the two parallel state dimensions and the departure cascade."""

from flask import Blueprint

from constants import ACCURACY_STATES, ALL_ROLES, LANES, TIMING_STATES
from db import base_row, db, minute_of_day, touch
from errors import fail, invalid
from middleware import (
    authenticate,
    get_loop,
    get_profile,
    get_restaurant,
    require_not_frozen,
    scope,
)
from response import ok
from routes.helpers import list_rows
from serialize import timer_loop as loop_json
from services import cascade
from services.loops import next_car_sequence, pin_targets, recompute_adjusted, recompute_segments
from services.rollup import preflight_tier, recompute
from validation import body_or_400, q_enum, q_str, raw_body, req_enum, req_int, req_str

bp = Blueprint("timer_loops", __name__)

LANES_BY_CONFIG = {
    "SINGLE": ("SINGLE",),
    "DUAL_TANDEM": ("LANE_A", "LANE_B"),
    "DUAL_PARALLEL": ("LANE_A", "LANE_B"),
}


def _loop_store(loop):
    return db.restaurants.get(loop["restaurant_id"])


@bp.route("/timer-loops", methods=["POST"])
def create_loop():
    actor = authenticate(("ShiftLeader",))
    scope(actor, raw_body().get("restaurant_id"))
    body = body_or_400()

    restaurant_id = req_str(body, "restaurant_id")
    daypart_profile_id = req_str(body, "daypart_profile_id")
    lane = req_enum(body, "lane", LANES)

    restaurant = get_restaurant(restaurant_id)
    profile = get_profile(daypart_profile_id)

    if profile["restaurant_id"] != restaurant_id:
        fail("ERR_RESTAURANT_MISMATCH", "the daypart profile belongs to another store")

    if lane not in LANES_BY_CONFIG[restaurant["lane_config"]]:
        invalid("lane %s is not available at a %s store"
                % (lane, restaurant["lane_config"]))

    require_not_frozen(restaurant)

    if profile["profile_state"] != "ACTIVE":
        fail("ERR_PROFILE_NOT_ACTIVE",
             "the daypart profile is %s, not ACTIVE" % profile["profile_state"])

    minute = minute_of_day(db.clock)
    if not (profile["start_minute"] <= minute < profile["end_minute"]):
        fail("ERR_DAYPART_WINDOW_MISMATCH",
             "minute-of-day %s is outside the profile window" % minute)

    pinned = pin_targets(restaurant, profile)

    row = base_row()
    row.update({
        "restaurant_id": restaurant_id,
        "daypart_profile_id": daypart_profile_id,
        "served_after_loop_id": None,
        "lane": lane,
        "car_sequence": next_car_sequence(restaurant_id),
        "arrive_at": db.clock,
        "greet_at": None,
        "order_complete_at": None,
        "merge_at": None,
        "window_arrive_at": None,
        "depart_at": None,
        "order_items_count": None,
        "greet_seconds": None,
        "order_seconds": None,
        "merge_wait_seconds": None,
        "pull_forward_seconds": None,
        "window_seconds": None,
        "total_seconds": None,
        "adjusted_total_seconds": None,
        "breach_flags": [],
        "timing_state": "OPEN",
        "accuracy_state": "PENDING",
        "abandon_reason": None,
    })
    row.update(pinned)
    db.timer_loops[row["id"]] = row
    return ok(loop_json(row), 201)


@bp.route("/timer-loops/<loop_id>/greet", methods=["POST"])
def greet_loop(loop_id):
    actor = authenticate(("ShiftLeader",))
    loop = get_loop(loop_id)
    scope(actor, loop["restaurant_id"])
    require_not_frozen(_loop_store(loop))

    if loop["timing_state"] != "OPEN":
        fail("ERR_INVALID_TIMER_STATE",
             "greet requires timing_state OPEN, found %s" % loop["timing_state"])

    loop["greet_at"] = db.clock
    loop["timing_state"] = "GREETED"
    recompute_segments(loop)
    touch(loop)
    return ok(loop_json(loop))


@bp.route("/timer-loops/<loop_id>/order-complete", methods=["POST"])
def order_complete_loop(loop_id):
    actor = authenticate(("ShiftLeader",))
    loop = get_loop(loop_id)
    scope(actor, loop["restaurant_id"])
    body = body_or_400()
    items = req_int(body, "order_items_count", minimum=1, maximum=40)

    require_not_frozen(_loop_store(loop))

    if loop["timing_state"] != "GREETED":
        fail("ERR_INVALID_TIMER_STATE",
             "order completion requires timing_state GREETED, found %s" % loop["timing_state"])

    loop["order_complete_at"] = db.clock
    loop["order_items_count"] = items
    loop["timing_state"] = "ORDERED"
    recompute_segments(loop)
    touch(loop)
    return ok(loop_json(loop))


@bp.route("/timer-loops/<loop_id>/window-arrive", methods=["POST"])
def window_arrive_loop(loop_id):
    actor = authenticate(("ShiftLeader",))
    loop = get_loop(loop_id)
    scope(actor, loop["restaurant_id"])
    restaurant = _loop_store(loop)
    require_not_frozen(restaurant)

    single = restaurant is not None and restaurant["lane_config"] == "SINGLE"
    allowed = ("MERGED", "ORDERED") if single else ("MERGED",)
    if loop["timing_state"] not in allowed:
        fail("ERR_INVALID_TIMER_STATE",
             "window arrival requires timing_state %s, found %s"
             % (" or ".join(allowed), loop["timing_state"]))

    loop["window_arrive_at"] = db.clock
    loop["timing_state"] = "AT_WINDOW"
    recompute_segments(loop)
    touch(loop)
    return ok(loop_json(loop))


@bp.route("/timer-loops/<loop_id>/depart", methods=["POST"])
def depart_loop(loop_id):
    actor = authenticate(("ShiftLeader",))
    loop = get_loop(loop_id)
    scope(actor, loop["restaurant_id"])
    restaurant = _loop_store(loop)
    require_not_frozen(restaurant)

    if loop["timing_state"] != "AT_WINDOW":
        fail("ERR_INVALID_TIMER_STATE",
             "departure requires timing_state AT_WINDOW, found %s" % loop["timing_state"])

    # Ladder 25 — prove the band table still covers the post-departure car rate
    # before anything is written.
    preflight_tier(restaurant, extra_closed=1)

    loop["depart_at"] = db.clock
    loop["timing_state"] = "CLOSED"
    if loop["accuracy_state"] == "PENDING":
        loop["accuracy_state"] = "VERIFIED"
    recompute_segments(loop)
    recompute_adjusted(loop)
    touch(loop)

    cascade.clear_live_pull_forwards(loop)
    cascade.release_committed_slot(loop)
    recompute_adjusted(loop)

    recompute(restaurant)
    return ok(loop_json(loop))


@bp.route("/timer-loops/<loop_id>/abandon", methods=["POST"])
def abandon_loop(loop_id):
    actor = authenticate(("ShiftLeader",))
    loop = get_loop(loop_id)
    scope(actor, loop["restaurant_id"])
    body = body_or_400()
    reason = req_str(body, "abandon_reason")

    restaurant = _loop_store(loop)
    require_not_frozen(restaurant)

    if loop["timing_state"] not in ("OPEN", "GREETED", "ORDERED", "MERGED", "AT_WINDOW"):
        fail("ERR_INVALID_TIMER_STATE",
             "abandonment is not available from timing_state %s" % loop["timing_state"])

    previous = loop["timing_state"]
    loop["timing_state"] = "ABANDONED"
    loop["abandon_reason"] = reason
    touch(loop)

    if previous == "ORDERED":
        cascade.forfeit_slots(loop, ("RESERVED",))
    elif previous in ("MERGED", "AT_WINDOW"):
        cascade.forfeit_slots(loop, ("RESERVED", "COMMITTED"))
    cascade.cancel_live_pull_forwards(loop)

    recompute(restaurant)
    return ok(loop_json(loop))


@bp.route("/timer-loops", methods=["GET"])
def list_loops():
    authenticate(ALL_ROLES)
    return list_rows(db.timer_loops, loop_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("daypart_profile_id", q_str("daypart_profile_id")),
        ("served_after_loop_id", q_str("served_after_loop_id")),
        ("lane", q_enum("lane", LANES)),
        ("timing_state", q_enum("timing_state", TIMING_STATES)),
        ("accuracy_state", q_enum("accuracy_state", ACCURACY_STATES)),
    ))


@bp.route("/timer-loops/<loop_id>", methods=["GET"])
def read_loop(loop_id):
    authenticate(ALL_ROLES)
    return ok(loop_json(get_loop(loop_id)))
