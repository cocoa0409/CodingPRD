"""Merge slots: the commit transition plus reads (awards live on the store)."""

from flask import Blueprint

from constants import ALL_ROLES, SLOT_STATES
from db import db, touch
from errors import fail
from middleware import authenticate, get_slot, require_not_frozen, scope
from response import ok
from routes.helpers import list_rows
from serialize import merge_slot as merge_slot_json
from services.loops import recompute_segments
from services.rollup import recompute
from validation import q_enum, q_str

bp = Blueprint("merge_slots", __name__)


@bp.route("/merge-slots/<slot_id>/commit", methods=["POST"])
def commit_slot(slot_id):
    actor = authenticate(("ShiftLeader",))
    slot = get_slot(slot_id)
    scope(actor, slot["restaurant_id"])
    restaurant = db.restaurants.get(slot["restaurant_id"])
    require_not_frozen(restaurant)

    if slot["slot_state"] != "RESERVED":
        fail("ERR_INVALID_SLOT_STATE",
             "commit requires slot_state RESERVED, found %s" % slot["slot_state"])

    loop = db.timer_loops.get(slot["timer_loop_id"])
    if loop is None or loop["timing_state"] != "ORDERED":
        fail("ERR_LOOP_NOT_MERGEABLE", "the awarded loop is no longer ORDERED")

    slot["slot_state"] = "COMMITTED"
    touch(slot)

    loop["merge_at"] = db.clock
    loop["timing_state"] = "MERGED"
    recompute_segments(loop)
    touch(loop)

    recompute(restaurant)
    return ok(merge_slot_json(slot))


@bp.route("/merge-slots", methods=["GET"])
def list_slots():
    authenticate(ALL_ROLES)
    return list_rows(db.merge_slots, merge_slot_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("timer_loop_id", q_str("timer_loop_id")),
        ("slot_state", q_enum("slot_state", SLOT_STATES)),
    ))


@bp.route("/merge-slots/<slot_id>", methods=["GET"])
def read_slot(slot_id):
    authenticate(ALL_ROLES)
    return ok(merge_slot_json(get_slot(slot_id)))
