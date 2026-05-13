"""Reservation endpoints."""

from datetime import timedelta

from flask import Blueprint, g

import db
from clock import format_iso, now
from errors import raise_error
from middleware import require_roles
from response import success
from validators import check_version, parse_json_body, require_str


bp = Blueprint("reservations", __name__)


HOLD_MINUTES = 15
MAX_STRIKES = 3


@bp.post("/reservations")
@require_roles({"EVDriver"})
def create_reservation():
    body = parse_json_body()
    pile_id = require_str(body, "pile_id")
    pile = db.piles.get(pile_id)
    if pile is None:
        raise_error("ERR_NOT_FOUND", "pile not found")

    member = db.members.get(g.user_id)
    if member is None:
        raise_error("ERR_AUTH_INVALID", "member missing")

    if int(member["no_show_strikes"]) >= MAX_STRIKES:
        raise_error("ERR_NO_SHOW_THRESHOLD_EXCEEDED", "too many no-shows")

    # Pile must be ON_SHELF and IDLE.
    if pile["lifecycle_state"] != "ON_SHELF" or pile["operational_state"] != "IDLE":
        raise_error("ERR_PILE_UNAVAILABLE", "pile not available")

    # At most one HELD reservation per pile.
    for existing in db.reservations.values():
        if existing["pile_id"] == pile_id and existing["status"] == "HELD":
            raise_error("ERR_PILE_ALREADY_RESERVED", "pile already reserved")

    created_at = now()
    expires_at = created_at + timedelta(minutes=HOLD_MINUTES)

    record = {
        "pile_id": pile_id,
        "member_id": g.user_id,
        "hold_expires_at": format_iso(expires_at),
        "status": "HELD",
        "no_show_penalty_cents": 0,
    }
    db.with_common_fields(record)
    # Pin created_at to the clock value so hold math is deterministic.
    record["created_at"] = format_iso(created_at)
    record["updated_at"] = record["created_at"]
    db.reservations[record["id"]] = record
    return success(db.public(record), status=201)


@bp.post("/reservations/<reservation_id>/cancel")
@require_roles({"EVDriver"})
def cancel_reservation(reservation_id: str):
    res = db.reservations.get(reservation_id)
    if res is None:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    body = parse_json_body()
    check_version(body, res)
    if res["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your reservation")
    if res["status"] != "HELD":
        raise_error("ERR_INVALID_STATE", "reservation not in HELD state")
    res["status"] = "CANCELLED"
    db.bump(res)
    return success(db.public(res))


@bp.get("/reservations/<reservation_id>")
@require_roles({"EVDriver", "PlatformOperator", "CustomerService"})
def get_reservation(reservation_id: str):
    res = db.reservations.get(reservation_id)
    if res is None:
        raise_error("ERR_NOT_FOUND", "reservation not found")
    if g.role == "EVDriver" and res["member_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "not your reservation")
    return success(db.public(res))
