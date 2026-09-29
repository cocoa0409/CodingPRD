"""Casting assignments: create/supersede, hold, confirm, release."""
from flask import Blueprint, g, request

from auth import ALL_ROLES, auth
from domain import (LIVE_CASTING_STATES, check_order_open, get_assignment, get_character,
                    get_order, get_talent, live_assignments, order_cut, rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_enum, v_int

bp = Blueprint("casting", __name__)

USAGE_VARIANTS = ("BUYOUT", "RESIDUAL")
CASTING_OPEN_ORDER_STATES = ("CASTING", "RECORDING")


@bp.post("/casting-assignments")
@auth("CastingDirector")
def create_assignment():
    data = body()
    order = get_order(data.get("order_id"))                 # rung 7, declaration order
    character = get_character(data.get("character_id"))
    talent = get_talent(data.get("talent_id"))
    usage_variant = v_enum(data, "usage_variant", USAGE_VARIANTS)     # rung 8
    agreed_rate = v_int(data, "agreed_rate_cents_per_hour", minimum=1)
    expected_version = v_int(data, "expected_order_version")

    check_order_open(order)                                  # rung 10
    if expected_version != order["version"]:                 # rung 12
        raise ApiError("ERR_STALE_ORDER_VERSION")
    if order["territory"] not in talent["licensed_territories"]:      # rung 15
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")
    if talent["status"] != "ACTIVE":                         # rung 16
        raise ApiError("ERR_TALENT_SUSPENDED")
    if talent["language_code"] != order["target_language"]:  # rung 17
        raise ApiError("ERR_TALENT_LANGUAGE_MISMATCH")
    cut = order_cut(order)                                   # rung 19
    if cut is None or character["title_id"] != cut["title_id"]:
        raise ApiError("ERR_CHARACTER_TITLE_MISMATCH")
    if agreed_rate < talent["base_rate_cents_per_hour"]:     # rung 24
        raise ApiError("ERR_RATE_BELOW_TALENT_FLOOR")
    for other in live_assignments(order["id"]):              # rung 25
        if (other["talent_id"] == talent["id"]
                and other["character_id"] != character["id"]
                and other["casting_status"] in LIVE_CASTING_STATES):
            raise ApiError("ERR_DUPLICATE_CASTING")

    row = new_row({
        "order_id": order["id"],
        "character_id": character["id"],
        "talent_id": talent["id"],
        "casting_status": "PROPOSED",
        "payment_status": "UNBILLED",
        "usage_variant": usage_variant,
        "agreed_rate_cents_per_hour": agreed_rate,
        "superseded_by_id": None,
        "recorded_minutes": 0,
        "retake_minutes": 0,
    })

    for other in live_assignments(order["id"]):
        if other["character_id"] != character["id"]:
            continue
        if other["casting_status"] not in LIVE_CASTING_STATES:
            continue
        other["superseded_by_id"] = row["id"]
        other["casting_status"] = "RELEASED"
        touch(other)

    db.assignments[row["id"]] = row
    touch(order)
    return created(serialize(row))


@bp.get("/casting-assignments/<assignment_id>")
@auth(*ALL_ROLES)
def read_assignment(assignment_id):
    return ok(serialize(get_assignment(assignment_id)))


@bp.get("/casting-assignments")
@auth(*ALL_ROLES)
def list_assignments():
    rows = list(db.assignments.values())
    for key in ("order_id", "character_id", "talent_id", "superseded_by_id",
                "casting_status", "payment_status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/casting-assignments/<assignment_id>/request-hold")
@auth("CastingDirector")
def request_hold(assignment_id):
    assignment = get_assignment(assignment_id)
    order = db.orders[assignment["order_id"]]
    check_order_open(order)                                   # rung 10
    if assignment["casting_status"] != "PROPOSED":            # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order["status"] not in CASTING_OPEN_ORDER_STATES:
        raise ApiError("ERR_INVALID_STATE")
    assignment["casting_status"] = "HOLD_REQUESTED"
    touch(assignment)
    return ok(serialize(assignment))


@bp.post("/casting-assignments/<assignment_id>/respond-hold")
@auth("VoiceTalentUser")
def respond_hold(assignment_id):
    assignment = get_assignment(assignment_id)
    if g.user_id != assignment["talent_id"]:                  # rung 4
        raise ApiError("ERR_TALENT_NOT_OWNER")
    data = body()
    response = v_enum(data, "response", ("ACCEPT", "DECLINE"))   # rung 8
    order = db.orders[assignment["order_id"]]
    check_order_open(order)                                   # rung 10
    if assignment["casting_status"] != "HOLD_REQUESTED":      # rung 11
        raise ApiError("ERR_INVALID_STATE")
    assignment["casting_status"] = "HELD" if response == "ACCEPT" else "DECLINED"
    touch(assignment)
    return ok(serialize(assignment))


@bp.post("/casting-assignments/<assignment_id>/confirm")
@auth("CastingDirector")
def confirm_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    order = db.orders[assignment["order_id"]]
    check_order_open(order)                                   # rung 10
    if assignment["casting_status"] != "HELD":                # rung 11
        raise ApiError("ERR_INVALID_STATE")
    if order["status"] not in CASTING_OPEN_ORDER_STATES:
        raise ApiError("ERR_INVALID_STATE")
    if assignment["superseded_by_id"] is not None:
        raise ApiError("ERR_INVALID_STATE")
    assignment["casting_status"] = "CONFIRMED"
    touch(assignment)
    return ok(serialize(assignment))


@bp.post("/casting-assignments/<assignment_id>/release")
@auth("CastingDirector")
def release_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    order = db.orders[assignment["order_id"]]
    check_order_open(order)                                   # rung 10
    if assignment["casting_status"] not in ("PROPOSED", "HOLD_REQUESTED", "HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE")                   # rung 11
    for session in db.sessions.values():
        if (session["casting_assignment_id"] == assignment["id"]
                and session["status"] in ("SCHEDULED", "CONFIRMED", "IN_PROGRESS")):
            raise ApiError("ERR_INVALID_STATE")
    assignment["casting_status"] = "RELEASED"
    touch(assignment)
    return ok(serialize(assignment))
