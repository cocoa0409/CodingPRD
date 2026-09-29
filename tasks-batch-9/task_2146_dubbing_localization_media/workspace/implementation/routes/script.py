"""Script adaptations: translate, adapt, submit-review, native review."""
from flask import Blueprint, g, request

import calc
from auth import ALL_ROLES, auth
from domain import (check_order_open, get_adaptation, get_order, order_adaptation,
                    order_cut, order_spec, rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_enum, v_int, v_string

bp = Blueprint("script", __name__)

SCRIPT_OPEN_ORDER_STATES = ("SCRIPT_IN_PROGRESS", "CASTING", "RECORDING")


def _stamp_provisional(adaptation, order):
    cut = order_cut(order)
    adaptation["provisional_fidelity_score"] = calc.provisional_fidelity_score(
        adaptation["declared_loop_count"], cut["loop_count"], order["priority_tier"])


def _stamp_final(adaptation, order):
    spec = order_spec(order)
    adaptation["final_fidelity_score"] = calc.final_fidelity_score(
        adaptation["measured_sync_deviation_ms_total"],
        adaptation["lines_over_deviation"],
        adaptation["declared_loop_count"],
        spec["max_lipsync_deviation_ms"],
        order["priority_tier"])


@bp.post("/script-adaptations")
@auth("Adaptor")
def create_adaptation():
    data = body()
    order = get_order(data.get("order_id"))        # rung 7
    check_order_open(order)                        # rung 10
    if order["status"] != "DRAFT":                 # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order_adaptation(order["id"]) is not None:
        raise ApiError("ERR_INVALID_STATE")

    row = new_row({
        "order_id": order["id"],
        "status": "DRAFT",
        "revision_round": 1,
        "adapted_by_user_id": None,
        "reviewed_by_user_id": None,
        "declared_loop_count": 0,
        "measured_sync_deviation_ms_total": 0,
        "lines_over_deviation": 0,
        "provisional_fidelity_score": None,
        "final_fidelity_score": None,
    })
    db.adaptations[row["id"]] = row
    order["status"] = "SCRIPT_IN_PROGRESS"
    touch(order)
    return created(serialize(row))


@bp.get("/script-adaptations/<adaptation_id>")
@auth(*ALL_ROLES)
def read_adaptation(adaptation_id):
    return ok(serialize(get_adaptation(adaptation_id)))


@bp.get("/script-adaptations")
@auth(*ALL_ROLES)
def list_adaptations():
    rows = list(db.adaptations.values())
    for key in ("order_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/script-adaptations/<adaptation_id>/translate")
@auth("Adaptor")
def translate(adaptation_id):
    adaptation = get_adaptation(adaptation_id)
    order = db.orders[adaptation["order_id"]]
    check_order_open(order)                                     # rung 10
    if adaptation["status"] != "DRAFT":                         # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order["status"] not in SCRIPT_OPEN_ORDER_STATES:
        raise ApiError("ERR_INVALID_STATE")
    adaptation["status"] = "TRANSLATED"
    touch(adaptation)
    return ok(serialize(adaptation))


@bp.post("/script-adaptations/<adaptation_id>/adapt")
@auth("Adaptor")
def adapt(adaptation_id):
    adaptation = get_adaptation(adaptation_id)
    data = body()
    declared = v_int(data, "declared_loop_count", minimum=0)    # rung 8
    order = db.orders[adaptation["order_id"]]
    check_order_open(order)                                     # rung 10
    if adaptation["status"] not in ("TRANSLATED", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_STATE")                     # rung 11
    if order["status"] not in SCRIPT_OPEN_ORDER_STATES:
        raise ApiError("ERR_INVALID_STATE")

    if adaptation["status"] == "REVISION_REQUESTED":
        adaptation["revision_round"] = adaptation["revision_round"] + 1
    adaptation["declared_loop_count"] = declared
    adaptation["adapted_by_user_id"] = g.user_id
    _stamp_provisional(adaptation, order)
    adaptation["status"] = "ADAPTED"
    touch(adaptation)
    return ok(serialize(adaptation))


@bp.post("/script-adaptations/<adaptation_id>/submit-review")
@auth("Adaptor")
def submit_review(adaptation_id):
    adaptation = get_adaptation(adaptation_id)
    data = body()
    measured = v_int(data, "measured_sync_deviation_ms_total", minimum=0)
    lines_over = v_int(data, "lines_over_deviation", minimum=0)
    order = db.orders[adaptation["order_id"]]
    check_order_open(order)                                     # rung 10
    if adaptation["status"] != "ADAPTED":                       # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if adaptation["declared_loop_count"] < 1:
        raise ApiError("ERR_INVALID_STATE")

    adaptation["measured_sync_deviation_ms_total"] = measured
    adaptation["lines_over_deviation"] = lines_over
    _stamp_final(adaptation, order)
    adaptation["status"] = "IN_REVIEW"
    touch(adaptation)
    if order["status"] == "SCRIPT_IN_PROGRESS":
        order["status"] = "CASTING"
        touch(order)
    return ok(serialize(adaptation))


@bp.post("/script-adaptations/<adaptation_id>/review")
@auth("NativeReviewer")
def review(adaptation_id):
    adaptation = get_adaptation(adaptation_id)
    data = body()
    decision = v_enum(data, "decision", ("APPROVE", "REQUEST_REVISION"))   # rung 8
    v_string(data, "notes", required=False, default=None, non_empty=False)
    order = db.orders[adaptation["order_id"]]
    check_order_open(order)                                                # rung 10
    if adaptation["status"] != "IN_REVIEW":                                # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if adaptation["adapted_by_user_id"] is not None and g.user_id == adaptation["adapted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")                        # rung 14

    if decision == "APPROVE":
        spec = order_spec(order)                                           # rung 29
        score = adaptation["final_fidelity_score"]
        if score is None or score < spec["min_fidelity_score"]:
            raise ApiError("ERR_FIDELITY_BELOW_SPEC")
        adaptation["reviewed_by_user_id"] = g.user_id
        adaptation["status"] = "APPROVED"
    else:
        adaptation["reviewed_by_user_id"] = g.user_id
        adaptation["status"] = "REVISION_REQUESTED"
    touch(adaptation)
    return ok(serialize(adaptation))
