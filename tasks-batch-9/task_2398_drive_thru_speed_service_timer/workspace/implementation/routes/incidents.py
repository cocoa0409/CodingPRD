"""Accuracy incidents: logging cascade, remake delivery and the two settlements."""

from flask import Blueprint

from constants import (
    ALL_ROLES,
    INCIDENT_STATES,
    INCIDENT_TYPES,
    PENALTY_SECONDS_BY_SEVERITY,
    REMAKE_COST_CENTS_BY_SEVERITY,
)
from db import base_row, db, snapshot, touch, touch_if_changed
from errors import fail
from middleware import (
    authenticate,
    get_incident,
    get_loop,
    get_staff,
    require_not_frozen,
    scope,
)
from response import ok
from routes.helpers import list_rows
from serialize import accuracy_incident as incident_json
from services import cascade
from services.loops import recompute_adjusted
from services.rollup import recompute
from validation import body_or_400, q_enum, q_str, req_enum, req_str

bp = Blueprint("incidents", __name__)

SEVERITY_BY_TYPE = {
    "ALLERGEN": "CRITICAL",
    "WRONG_ITEM": "MAJOR",
    "MISSING_ITEM": "MAJOR",
    "WRONG_SIZE": "MINOR",
}

LOGGABLE_TIMING_STATES = ("ORDERED", "MERGED", "AT_WINDOW", "CLOSED")


def _store_of(incident):
    return db.restaurants.get(incident["restaurant_id"])


def _loop_of(incident):
    return db.timer_loops.get(incident["timer_loop_id"])


@bp.route("/accuracy-incidents", methods=["POST"])
def create_incident():
    actor = authenticate(("ShiftLeader",))
    scope(actor, None)
    body = body_or_400()

    timer_loop_id = req_str(body, "timer_loop_id")
    logged_by_staff_id = req_str(body, "logged_by_staff_id")
    incident_type = req_enum(body, "incident_type", INCIDENT_TYPES)

    loop = get_loop(timer_loop_id)
    scope(actor, loop["restaurant_id"])
    reporter = get_staff(logged_by_staff_id)

    if reporter["restaurant_id"] != loop["restaurant_id"]:
        fail("ERR_RESTAURANT_MISMATCH", "the reporter belongs to another store")

    restaurant = db.restaurants.get(loop["restaurant_id"])
    require_not_frozen(restaurant)

    if loop["timing_state"] not in LOGGABLE_TIMING_STATES:
        fail("ERR_LOOP_HAS_NO_ORDER",
             "the car has not ordered yet (timing_state %s)" % loop["timing_state"])
    if loop["accuracy_state"] not in ("PENDING", "VERIFIED"):
        fail("ERR_REMAKE_ALREADY_OPEN",
             "the loop already carries an unresolved remake (%s)" % loop["accuracy_state"])

    severity = SEVERITY_BY_TYPE[incident_type]

    row = base_row()
    row.update({
        "restaurant_id": loop["restaurant_id"],
        "timer_loop_id": loop["id"],
        "logged_by_staff_id": logged_by_staff_id,
        "remade_by_staff_id": None,
        "incident_type": incident_type,
        "severity": severity,
        "penalty_seconds": PENALTY_SECONDS_BY_SEVERITY[severity],
        "remake_cost_cents": REMAKE_COST_CENTS_BY_SEVERITY[severity],
        "incident_state": "LOGGED",
        "settlement_state": "ACCRUED",
        "waiver_reason": None,
    })
    db.accuracy_incidents[row["id"]] = row

    loop["accuracy_state"] = "REMAKE_OPEN"
    recompute_adjusted(loop)
    touch(loop)

    cascade.auto_issue_remake_pull_forward(loop)
    recompute(restaurant)
    return ok(incident_json(row), 201)


@bp.route("/accuracy-incidents/<incident_id>/deliver-remake", methods=["POST"])
def deliver_remake(incident_id):
    actor = authenticate(("ShiftLeader",))
    incident = get_incident(incident_id)
    scope(actor, incident["restaurant_id"])
    body = body_or_400()
    remade_by_staff_id = req_str(body, "remade_by_staff_id")

    remaker = get_staff(remade_by_staff_id)
    if remaker["restaurant_id"] != incident["restaurant_id"]:
        fail("ERR_RESTAURANT_MISMATCH", "the remaking team member belongs to another store")

    restaurant = _store_of(incident)
    require_not_frozen(restaurant)

    if incident["incident_state"] != "LOGGED":
        fail("ERR_INVALID_INCIDENT_STATE",
             "remake delivery requires incident_state LOGGED, found %s"
             % incident["incident_state"])

    if remade_by_staff_id == incident["logged_by_staff_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the reporter may not be credited with their own remake")

    incident["incident_state"] = "REMADE"
    incident["remade_by_staff_id"] = remade_by_staff_id
    touch(incident)

    loop = _loop_of(incident)
    if loop is not None:
        loop["accuracy_state"] = "REMADE"
        recompute_adjusted(loop)
        touch(loop)

    recompute(restaurant)
    return ok(incident_json(incident))


@bp.route("/accuracy-incidents/<incident_id>/close", methods=["POST"])
def close_incident(incident_id):
    authenticate(("AccuracyAuditor",))
    incident = get_incident(incident_id)
    restaurant = _store_of(incident)
    require_not_frozen(restaurant)

    if incident["incident_state"] != "REMADE":
        fail("ERR_INVALID_INCIDENT_STATE",
             "closure requires incident_state REMADE, found %s" % incident["incident_state"])

    incident["incident_state"] = "CLOSED"
    incident["settlement_state"] = "CHARGED"
    touch(incident)

    loop = _loop_of(incident)
    if loop is not None:
        before = snapshot(loop)
        loop["accuracy_state"] = "VERIFIED"
        recompute_adjusted(loop)
        touch_if_changed(loop, before)

    recompute(restaurant)
    return ok(incident_json(incident))


@bp.route("/accuracy-incidents/<incident_id>/waive", methods=["POST"])
def waive_incident(incident_id):
    authenticate(("AccuracyAuditor",))
    incident = get_incident(incident_id)
    body = body_or_400()
    waiver_reason = req_str(body, "waiver_reason")

    restaurant = _store_of(incident)
    require_not_frozen(restaurant)

    if incident["incident_state"] != "LOGGED":
        fail("ERR_INVALID_INCIDENT_STATE",
             "waiver requires incident_state LOGGED, found %s" % incident["incident_state"])

    if incident["severity"] == "CRITICAL":
        fail("ERR_ALLERGEN_WAIVER_FORBIDDEN", "a CRITICAL incident can never be waived")

    incident["incident_state"] = "WAIVED"
    incident["settlement_state"] = "REVERSED"
    incident["waiver_reason"] = waiver_reason
    touch(incident)

    loop = _loop_of(incident)
    if loop is not None:
        before = snapshot(loop)
        loop["accuracy_state"] = "WAIVED"
        recompute_adjusted(loop)
        touch_if_changed(loop, before)

    recompute(restaurant)
    return ok(incident_json(incident))


@bp.route("/accuracy-incidents", methods=["GET"])
def list_incidents():
    authenticate(ALL_ROLES)
    return list_rows(db.accuracy_incidents, incident_json, (
        ("restaurant_id", q_str("restaurant_id")),
        ("timer_loop_id", q_str("timer_loop_id")),
        ("logged_by_staff_id", q_str("logged_by_staff_id")),
        ("remade_by_staff_id", q_str("remade_by_staff_id")),
        ("incident_state", q_enum("incident_state", INCIDENT_STATES)),
    ))


@bp.route("/accuracy-incidents/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    authenticate(ALL_ROLES)
    return ok(incident_json(get_incident(incident_id)))
