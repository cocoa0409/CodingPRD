"""Passenger notification obligations: the manual entry point and the dispatch gate."""
from flask import Blueprint

import calc
import cascades
import db
import reqval as rv
from db import mark, store
from errors import ApiError
from middleware import authenticate
from response import ok, written
from routes.common import READ_ROLES, list_response, read_one
from util import dt_of

bp = Blueprint("notifications", __name__)

OFFICER = ("ComplianceOfficer",)
INSUFFICIENT_FOR_MANDATORY = ("SMS",)


@bp.post("/notification-obligations")
def create_obligation():
    authenticate(OFFICER)
    payload = rv.body()
    leg_id = rv.req_str(payload, "flight_leg_id", 1)
    trigger = rv.req_enum(payload, "trigger_kind", "trigger_kind")
    magnitude = rv.req_int(payload, "change_magnitude_minutes", 0)
    leg = store.require("flight_legs", leg_id)
    if cascades.booked_total(leg) <= 0 or magnitude < calc.MIN_MAGNITUDE_MINUTES:
        rv.bad("No notification is owed: the leg carries no bookings or the change is too small.")
    row = cascades.raise_obligation(leg, trigger, magnitude)
    # A hand-raised obligation records no pre-change times, so no cascade can
    # ever show the change as reverted and waive it.
    row["_prev_dep_utc"] = None
    row["_prev_arr_utc"] = None
    return written(row, 201)


@bp.get("/notification-obligations/<notification_obligation_id>")
def get_obligation(notification_obligation_id):
    return ok(read_one("notification_obligations", notification_obligation_id))


@bp.get("/notification-obligations")
def list_obligations():
    authenticate(READ_ROLES)
    return list_response("notification_obligations", [
        ("flight_leg_id", rv.q_str("flight_leg_id")),
        ("trigger_kind", rv.q_enum("trigger_kind", "trigger_kind")),
        ("obligation_tier", rv.q_enum("obligation_tier", "obligation_tier")),
        ("status", rv.q_enum("status", "obligation_status")),
        ("late_dispatch", rv.q_bool("late_dispatch")),
    ])


@bp.post("/notification-obligations/<notification_obligation_id>/dispatch")
def dispatch_obligation(notification_obligation_id):
    authenticate(OFFICER)
    obligation = store.require("notification_obligations", notification_obligation_id)
    payload = rv.body()
    channel = rv.req_enum(payload, "channel", "channel")
    reference = rv.opt_str(payload, "regulator_reference", 1, 120)

    if obligation["status"] != "PENDING":
        raise ApiError("ERR_NOTIFICATION_STATE_INVALID")
    if (
        obligation["obligation_tier"] == "MANDATORY_REACCOMMODATION"
        and channel in INSUFFICIENT_FOR_MANDATORY
    ):
        raise ApiError("ERR_NOTIFICATION_CHANNEL_INSUFFICIENT")
    late = db.now() > dt_of(obligation["notify_deadline_utc"])
    if late and reference is None:
        raise ApiError("ERR_LATE_NOTIFICATION_UNREFERENCED")

    obligation["status"] = "DISPATCHED"
    obligation["dispatched_channel"] = channel
    obligation["regulator_reference"] = reference
    obligation["late_dispatch"] = late
    mark(obligation)
    return written(obligation)
