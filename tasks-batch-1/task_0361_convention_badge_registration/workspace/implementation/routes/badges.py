"""Badge lifecycle endpoints: pickup, print, transfer, void (PRD §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import common
import db
import errors
import util
from middleware import authenticate, authorize
from services import calc, lookup, state
import response

bp = Blueprint("badges", __name__)

READ_ROLES = {"ConventionAdmin", "RegistrationAgent", "Attendee"}
MAX_TRANSFERS = 2


def _convention_for_badge(badge):
    order = db.orders[badge["order_id"]]
    return db.conventions[order["convention_id"]]


@bp.route("/badges/<bid>", methods=["GET"])
def get_badge(bid):
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    badge = lookup.badge(bid)
    lookup.require_attendee_owns(role, user_id, badge["holder_attendee_id"])
    return response.success(common.serialize(badge), 200)


@bp.route("/badges", methods=["GET"])
def list_badges():
    user_id, role = authenticate()
    authorize(role, READ_ROLES)
    rows = list(db.badges.values())
    order_filter = request.args.get("order_id")
    tt_filter = request.args.get("ticket_type_id")
    holder_filter = request.args.get("holder_attendee_id")
    if order_filter is not None:
        rows = [b for b in rows if b["order_id"] == order_filter]
    if tt_filter is not None:
        rows = [b for b in rows if b["ticket_type_id"] == tt_filter]
    if holder_filter is not None:
        rows = [b for b in rows if b["holder_attendee_id"] == holder_filter]
    if role == "Attendee":
        rows = [b for b in rows if b["holder_attendee_id"] == user_id]
    items, limit, offset, total = common.paginate(rows)
    return response.success_list(items, limit, offset, total)


@bp.route("/badges/<bid>/pickup", methods=["POST"])
def pickup_badge(bid):
    _, role = authenticate()
    authorize(role, {"RegistrationAgent"})
    badge = lookup.badge(bid)

    if badge["status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "Badge is not ISSUED")

    conv = _convention_for_badge(badge)
    event_start = util.parse_iso(conv["event_start_utc"])
    window_open = event_start - timedelta(hours=calc.PICKUP_WINDOW_HOURS)
    if clock.now() < window_open:
        raise errors.err(errors.ERR_PICKUP_WINDOW_CLOSED, "On-site window not open")

    badge["status"] = "PICKED_UP"
    badge["rfid_status"] = "ENCODED"
    badge["rfid_uid"] = util.new_id()
    common.touch(badge)
    return response.success(common.serialize(badge), 200)


@bp.route("/badges/<bid>/print", methods=["POST"])
def print_badge(bid):
    _, role = authenticate()
    authorize(role, {"RegistrationAgent"})
    badge = lookup.badge(bid)

    if badge["status"] != "PICKED_UP":
        raise errors.err(errors.ERR_INVALID_STATE, "Badge is not PICKED_UP")
    # rfid_status must be ENCODED to print (PRD §3.5).
    if badge["rfid_status"] != "ENCODED":
        raise errors.err(errors.ERR_INVALID_STATE, "Badge RFID is not ENCODED")

    conv = _convention_for_badge(badge)
    event_start = util.parse_iso(conv["event_start_utc"])
    window_open = event_start - timedelta(hours=calc.PICKUP_WINDOW_HOURS)
    if clock.now() < window_open:
        raise errors.err(errors.ERR_PICKUP_WINDOW_CLOSED, "On-site window not open")

    badge["status"] = "PRINTED"
    common.touch(badge)
    return response.success(common.serialize(badge), 200)


@bp.route("/badges/<bid>/transfer", methods=["POST"])
def transfer_badge(bid):
    user_id, role = authenticate()
    authorize(role, {"Attendee", "RegistrationAgent"})
    badge = lookup.badge(bid)
    # Ownership: current holder (Attendee) may transfer their own badge (PRD §2.1).
    lookup.require_attendee_owns(role, user_id, badge["holder_attendee_id"])

    # Banned check on the acting/holder attendee (PRD §2.9 step 4).
    holder = db.attendees.get(badge["holder_attendee_id"])
    if holder is not None and holder["status"] == "BANNED":
        raise errors.err(errors.ERR_ATTENDEE_BANNED, "Attendee is banned")

    body = common.get_body()
    new_holder_id = common.require_str(body, "new_holder_attendee_id")
    new_holder = lookup.attendee(new_holder_id)

    # Transfer limit (PRD §3.5): badge must be ISSUED and transfer_count < MAX_TRANSFERS.
    if badge["status"] != "ISSUED" or badge["transfer_count"] >= MAX_TRANSFERS:
        raise errors.err(errors.ERR_TRANSFER_LIMIT, "Transfer not allowed")

    badge["holder_attendee_id"] = new_holder_id
    badge["transfer_count"] = badge["transfer_count"] + 1
    common.touch(badge)
    return response.success(common.serialize(badge), 200)


@bp.route("/badges/<bid>/void", methods=["POST"])
def void_badge(bid):
    _, role = authenticate()
    authorize(role, {"RegistrationAgent", "ConventionAdmin"})
    badge = lookup.badge(bid)

    if badge["status"] not in {"ISSUED", "PICKED_UP", "PRINTED"}:
        raise errors.err(errors.ERR_INVALID_STATE, "Badge cannot be voided from its current state")

    conv = _convention_for_badge(badge)
    tt = db.ticket_types[badge["ticket_type_id"]]

    state.void_badge(badge)
    # Recompute counters downward from the surviving badge set (PRD §3.5).
    state.recompute_ticket_type_count(tt)
    state.recompute_convention_count(conv)
    return response.success(common.serialize(badge), 200)
