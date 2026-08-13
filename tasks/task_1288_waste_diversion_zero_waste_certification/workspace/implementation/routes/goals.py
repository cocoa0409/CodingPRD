"""SiteGoal endpoints."""

from flask import Blueprint

from db import base_record, store, touch
from errors import (
    ApiError,
    ERR_GOAL_WINDOW_OVERLAP,
    ERR_INVALID_STATE,
    ERR_WINDOW_INVALID,
    not_found,
)
from middleware import (
    no_input,
    ALL_ROLES,
    authenticate,
    check_unknown,
    f_date,
    f_enum,
    f_num,
    f_str,
    get_body,
)
from response import success_list, success_object
from services.lifecycle import pub_goal
from util import GOAL_METRICS, GOAL_STATUSES, apply_filters, paginate, sort_items

bp = Blueprint("goals", __name__)


@bp.route("/goals", methods=["POST"])
def create_goal():
    authenticate(["SustainabilityManager"])
    b = get_body()
    check_unknown(b, ["site_id", "metric", "target_value",
                      "window_start", "window_end"])
    site_id = f_str(b, "site_id")
    metric = f_enum(b, "metric", GOAL_METRICS)
    target = f_num(b, "target_value")
    ws = f_date(b, "window_start")
    we = f_date(b, "window_end")

    if site_id not in store.sites:
        raise not_found("Site not found")

    # Overlap guard (layer 8): no overlapping ACTIVE goal for the same
    # site+metric; half-open windows, adjacency allowed.
    for o in store.goals.values():
        if (o["site_id"] == site_id and o["metric"] == metric
                and o["status"] == "ACTIVE"
                and o["window_start"] < we and ws < o["window_end"]):
            raise ApiError(ERR_GOAL_WINDOW_OVERLAP, 409,
                           "An ACTIVE goal overlaps this site and metric window")

    # Window validity (layer 10): half-open, start strictly before end.
    if ws >= we:
        raise ApiError(ERR_WINDOW_INVALID, 422,
                       "window_start must be earlier than window_end")

    rec = base_record({
        "site_id": site_id,
        "metric": metric,
        "target_value": target,
        "window_start": ws,
        "window_end": we,
        "status": "ACTIVE",
    })
    store.goals[rec["id"]] = rec
    return success_object(pub_goal(rec), 201)


@bp.route("/goals/<goal_id>", methods=["GET"])
def get_goal(goal_id):
    authenticate(ALL_ROLES)
    rec = store.goals.get(goal_id)
    if rec is None:
        raise not_found("Goal not found")
    return success_object(pub_goal(rec))


@bp.route("/goals", methods=["GET"])
def list_goals():
    authenticate(ALL_ROLES)
    items = apply_filters(store.goals.values(), [
        ("site_id", "site_id", None),
        ("metric", "metric", GOAL_METRICS),
        ("status", "status", GOAL_STATUSES),
    ])
    page, meta = paginate(sort_items(items))
    return success_list([pub_goal(g) for g in page], meta)


@bp.route("/goals/<goal_id>/cancel", methods=["POST"])
def cancel_goal(goal_id):
    authenticate(["SustainabilityManager"])
    no_input(get_body())
    g = store.goals.get(goal_id)
    if g is None:
        raise not_found("Goal not found")
    if g["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Goal is not ACTIVE")
    g["status"] = "CANCELLED"
    touch(g)
    return success_object(pub_goal(g))
