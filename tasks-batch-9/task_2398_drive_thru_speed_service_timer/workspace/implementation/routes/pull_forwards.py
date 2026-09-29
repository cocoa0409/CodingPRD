"""Pull-forward orders: the cyclic ISSUED <-> PARKED escalation ladder."""

from flask import Blueprint

from constants import ALL_ROLES, PF_MAX_ESCALATIONS, PF_REASONS, PF_STATES
from db import base_row, db, snapshot, touch, touch_if_changed
from errors import fail
from middleware import authenticate, get_loop, get_pull_forward, require_not_frozen, scope
from response import ok
from routes.helpers import list_rows
from serialize import pull_forward_order as pf_json
from services import cascade
from services.loops import live_pull_forwards, recompute_adjusted
from services.rollup import recompute
from validation import body_or_400, opt_int, q_enum, q_str, req_enum, req_str

bp = Blueprint("pull_forwards", __name__)


def _loop_of(order):
    return db.timer_loops.get(order["timer_loop_id"])


def _store_of(order):
    return db.restaurants.get(order["restaurant_id"])


@bp.route("/pull-forward-orders", methods=["POST"])
def create_pull_forward():
    actor = authenticate(("ShiftLeader",))
    scope(actor, None)
    body = body_or_400()

    timer_loop_id = req_str(body, "timer_loop_id")
    reason = req_enum(body, "reason", PF_REASONS)
    lag_seconds = opt_int(body, "lag_seconds", minimum=0, maximum=900, default=0)

    loop = get_loop(timer_loop_id)
    scope(actor, loop["restaurant_id"])

    restaurant = db.restaurants.get(loop["restaurant_id"])
    require_not_frozen(restaurant)

    if live_pull_forwards(loop["id"]):
        fail("ERR_PULL_FORWARD_ALREADY_OPEN",
             "this loop already carries a live pull-forward order")

    row = base_row()
    row.update({
        "restaurant_id": loop["restaurant_id"],
        "timer_loop_id": loop["id"],
        "reason": reason,
        "lag_seconds": lag_seconds,
        "issued_at": db.clock,
        "reissued_at": None,
        "cleared_at": None,
        "escalation_count": 0,
        "pf_state": "ISSUED",
    })
    db.pull_forward_orders[row["id"]] = row

    cascade.forfeit_slots(loop, ("RESERVED",))
    recompute(restaurant)
    return ok(pf_json(row), 201)


@bp.route("/pull-forward-orders/<pf_id>/park", methods=["POST"])
def park_pull_forward(pf_id):
    actor = authenticate(("ShiftLeader",))
    order = get_pull_forward(pf_id)
    scope(actor, order["restaurant_id"])
    require_not_frozen(_store_of(order))

    if order["pf_state"] != "ISSUED":
        fail("ERR_INVALID_PULL_FORWARD_STATE",
             "parking requires pf_state ISSUED, found %s" % order["pf_state"])

    order["pf_state"] = "PARKED"
    touch(order)
    return ok(pf_json(order))


@bp.route("/pull-forward-orders/<pf_id>/reissue", methods=["POST"])
def reissue_pull_forward(pf_id):
    actor = authenticate(("ShiftLeader",))
    order = get_pull_forward(pf_id)
    scope(actor, order["restaurant_id"])
    require_not_frozen(_store_of(order))

    if order["pf_state"] != "PARKED":
        fail("ERR_INVALID_PULL_FORWARD_STATE",
             "reissue requires pf_state PARKED, found %s" % order["pf_state"])

    if order["escalation_count"] > PF_MAX_ESCALATIONS - 1:
        fail("ERR_PULL_FORWARD_ESCALATION_LIMIT",
             "a pull-forward order may be reissued at most %s times" % PF_MAX_ESCALATIONS)

    order["pf_state"] = "ISSUED"
    order["reissued_at"] = db.clock
    order["escalation_count"] = order["escalation_count"] + 1
    touch(order)

    loop = _loop_of(order)
    if loop is not None:
        before = snapshot(loop)
        recompute_adjusted(loop)
        touch_if_changed(loop, before)

    return ok(pf_json(order))


@bp.route("/pull-forward-orders/<pf_id>/clear", methods=["POST"])
def clear_pull_forward(pf_id):
    actor = authenticate(("ShiftLeader",))
    order = get_pull_forward(pf_id)
    scope(actor, order["restaurant_id"])
    require_not_frozen(_store_of(order))

    if order["pf_state"] not in ("ISSUED", "PARKED"):
        fail("ERR_INVALID_PULL_FORWARD_STATE",
             "clearing requires pf_state ISSUED or PARKED, found %s" % order["pf_state"])

    order["pf_state"] = "CLEARED"
    order["cleared_at"] = db.clock
    touch(order)
    return ok(pf_json(order))


@bp.route("/pull-forward-orders", methods=["GET"])
def list_pull_forwards():
    authenticate(ALL_ROLES)
    return list_rows(db.pull_forward_orders, pf_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("timer_loop_id", q_str("timer_loop_id")),
        ("pf_state", q_enum("pf_state", PF_STATES)),
    ))


@bp.route("/pull-forward-orders/<pf_id>", methods=["GET"])
def read_pull_forward(pf_id):
    authenticate(ALL_ROLES)
    return ok(pf_json(get_pull_forward(pf_id)))
