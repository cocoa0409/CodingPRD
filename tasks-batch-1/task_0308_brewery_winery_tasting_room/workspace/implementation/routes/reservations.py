"""Reservation routes (PRD §3.10). Table holds with half-open overlap check."""
from flask import Blueprint, request

import calculations as calc
from db import db, common_fields, touch
from errors import err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_TABLE_DOUBLE_BOOKED
from middleware import authenticate, authorize
from response import success
from serialize import public
from validate import (
    get_json_body, require_str, require_positive_int, require_enum,
    opt_bool, get_or_404, resolve_winery_fk,
)
from pagination import paginate, sorted_by_creation
from util import parse_datetime

bp = Blueprint("reservations", __name__)


def _new_reservation(winery_id, table_code, party_size, starts_at, ends_at, is_event, deposit_cents):
    r = common_fields()
    r.update({
        "winery_id": winery_id,
        "table_code": table_code,
        "party_size": party_size,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_event": is_event,
        "deposit_cents": deposit_cents,
        "status": "REQUESTED",
    })
    return r


@bp.route("/reservations", methods=["POST"])
def create_reservation():
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    table_code = require_str(body, "table_code")
    party_size = require_positive_int(body, "party_size")
    starts_at_raw = require_str(body, "starts_at")
    ends_at_raw = require_str(body, "ends_at")
    is_event = opt_bool(body, "is_event", False)
    starts_at = parse_datetime(starts_at_raw, "starts_at")
    ends_at = parse_datetime(ends_at_raw, "ends_at")
    if ends_at <= starts_at:
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    deposit_cents = calc.event_deposit(party_size, is_event)
    with db.lock:
        resolve_winery_fk(winery_id)
        r = _new_reservation(winery_id, table_code, party_size, starts_at_raw,
                             ends_at_raw, is_event, deposit_cents)
        db.reservations[r["id"]] = r
        return success(public(r), status=201)


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff", "ComplianceOfficer"])
    with db.lock:
        items = list(db.reservations.values())
        winery_id = request.args.get("winery_id")
        table_code = request.args.get("table_code")
        status = request.args.get("status")
        if winery_id is not None:
            items = [r for r in items if r["winery_id"] == winery_id]
        if table_code is not None:
            items = [r for r in items if r["table_code"] == table_code]
        if status is not None:
            items = [r for r in items if r["status"] == status]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(r) for r in page], pagination=pg)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    with db.lock:
        r = get_or_404(db.reservations, reservation_id)
        return success(public(r))


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: touching (a_end == b_start) does not conflict."""
    return a_start < b_end and b_start < a_end


@bp.route("/reservations/<reservation_id>/transitions", methods=["POST"])
def transition_reservation(reservation_id):
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    with db.lock:
        r = get_or_404(db.reservations, reservation_id)
        body = get_json_body()
        action = require_enum(body, "action",
                              {"CONFIRM", "SEAT", "COMPLETE", "MARK_NO_SHOW", "CANCEL"})

        if action == "CONFIRM":
            if r["status"] != "REQUESTED":
                raise err(ERR_INVALID_STATE, "Reservation is not REQUESTED")
            r_start = parse_datetime(r["starts_at"], "starts_at")
            r_end = parse_datetime(r["ends_at"], "ends_at")
            for other in db.reservations.values():
                if other["id"] == r["id"]:
                    continue
                if other["winery_id"] != r["winery_id"]:
                    continue
                if other["table_code"] != r["table_code"]:
                    continue
                if other["status"] not in ("CONFIRMED", "SEATED"):
                    continue
                o_start = parse_datetime(other["starts_at"], "starts_at")
                o_end = parse_datetime(other["ends_at"], "ends_at")
                if _overlaps(r_start, r_end, o_start, o_end):
                    raise err(ERR_TABLE_DOUBLE_BOOKED, "Table is double-booked for this window")
            r["status"] = "CONFIRMED"
            touch(r)

        elif action == "SEAT":
            if r["status"] != "CONFIRMED":
                raise err(ERR_INVALID_STATE, "Reservation is not CONFIRMED")
            r["status"] = "SEATED"
            touch(r)

        elif action == "COMPLETE":
            if r["status"] != "SEATED":
                raise err(ERR_INVALID_STATE, "Reservation is not SEATED")
            r["status"] = "COMPLETED"
            touch(r)

        elif action == "MARK_NO_SHOW":
            if r["status"] != "CONFIRMED":
                raise err(ERR_INVALID_STATE, "Reservation is not CONFIRMED")
            r["status"] = "NO_SHOW"
            touch(r)

        else:  # CANCEL
            if r["status"] not in ("REQUESTED", "CONFIRMED"):
                raise err(ERR_INVALID_STATE, "Reservation cannot be cancelled from its current state")
            r["status"] = "CANCELLED"
            touch(r)

        return success(public(r))
