"""Reservation endpoints + state machine (PRD §3.3, §3.4, §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response
from services import calc
from services.intervals import overlaps
from services.reservation_ops import release_held_vehicle

bp = Blueprint("reservations", __name__)


def _available_count(class_id, location_id):
    return sum(
        1
        for v in db.vehicles.values()
        if v["class_id"] == class_id
        and v["location_id"] == location_id
        and v["status"] == "AVAILABLE"
    )


def _fleet_size(class_id, location_id):
    """Location's fleet of that class = non-RETIRED vehicles at that location."""
    return sum(
        1
        for v in db.vehicles.values()
        if v["class_id"] == class_id
        and v["location_id"] == location_id
        and v["status"] != "RETIRED"
    )


@bp.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = get_principal()
    require_roles(role, {"RentalAgent", "Member"})
    body = request.get_json(silent=True) or {}

    member_id = util.require_str(body, "member_id")
    # Member ownership: a Member may book only for their own member_id.
    if role == "Member" and user_id != member_id:
        raise err("ERR_FORBIDDEN", "members may only book for their own member_id")

    pickup_location_id = util.require_str(body, "pickup_location_id")
    dropoff_location_id = util.require_str(body, "dropoff_location_id")
    class_id = util.require_str(body, "class_id")
    pickup_at = util.require_str(body, "pickup_at")
    dropoff_at = util.require_str(body, "dropoff_at")
    ldw = util.optional_bool(body, "ldw_selected", default=False)
    pai = util.optional_bool(body, "pai_selected", default=False)

    # Existence (left to right per the referenceable order): member, locations, class.
    lookup.get_member(member_id)
    lookup.get_location(pickup_location_id)
    lookup.get_location(dropoff_location_id)
    lookup.get_vehicle_class(class_id)

    # Well-formedness: dropoff strictly after pickup.
    pickup_dt = util.parse_iso8601(pickup_at)
    dropoff_dt = util.parse_iso8601(dropoff_at)
    if not (dropoff_dt > pickup_dt):
        raise err("ERR_INVALID_REQUEST", "dropoff_at must be strictly after pickup_at")

    rental_days = calc.compute_rental_days(pickup_at, dropoff_at)

    rec = util.stamp_new(
        {
            "member_id": member_id,
            "pickup_location_id": pickup_location_id,
            "dropoff_location_id": dropoff_location_id,
            "class_id": class_id,
            "pickup_at": pickup_at,
            "dropoff_at": dropoff_at,
            "rental_days": rental_days,
            "ldw_selected": ldw,
            "pai_selected": pai,
            "status": "QUOTED",
            "quoted_total_cents": None,
            "hold_expires_at": None,
        }
    )
    db.reservations[rec["id"]] = rec
    return object_response(serialize.reservation(rec), 201)


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})

    pickup_location_id = request.args.get("pickup_location_id")
    dropoff_location_id = request.args.get("dropoff_location_id")
    class_id = request.args.get("class_id")
    status = request.args.get("status")

    matches = [
        r
        for r in db.reservations.values()
        if (pickup_location_id is None or r["pickup_location_id"] == pickup_location_id)
        and (dropoff_location_id is None or r["dropoff_location_id"] == dropoff_location_id)
        and (class_id is None or r["class_id"] == class_id)
        and (status is None or r["status"] == status)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.reservation(r) for r in page], limit, offset, total, 200
    )


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    user_id, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_reservation(reservation_id)
    if role == "Member" and user_id != rec["member_id"]:
        raise err("ERR_FORBIDDEN", "members may only read their own reservations")
    return object_response(serialize.reservation(rec), 200)


@bp.route("/reservations/<reservation_id>/rental-agreements", methods=["GET"])
def list_reservation_agreements(reservation_id):
    user_id, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_reservation(reservation_id)
    if role == "Member" and user_id != rec["member_id"]:
        raise err("ERR_FORBIDDEN", "members may only read their own reservations")

    matches = [
        a for a in db.agreements.values() if a["reservation_id"] == reservation_id
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.agreement(a) for a in page], limit, offset, total, 200
    )


@bp.route("/reservations/<reservation_id>/upgrade", methods=["POST"])
def upgrade_reservation(reservation_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    body = request.get_json(silent=True) or {}

    rec = lookup.get_reservation(reservation_id)
    new_class_id = util.require_str(body, "class_id")
    new_class = lookup.get_vehicle_class(new_class_id)

    # State: upgrade only while QUOTED or CONFIRMED.
    if rec["status"] not in ("QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "reservation must be QUOTED or CONFIRMED to upgrade")

    current_class = db.vehicle_classes[rec["class_id"]]
    if new_class["tier_rank"] <= current_class["tier_rank"]:
        raise err("ERR_NOT_AN_UPGRADE", "target class tier_rank must be strictly higher")

    rec["class_id"] = new_class_id
    # If already CONFIRMED, recompute the frozen estimate against the new class.
    if rec["status"] == "CONFIRMED":
        rec["quoted_total_cents"] = calc.reservation_quote(rec)
    util.touch(rec)
    return object_response(serialize.reservation(rec), 200)


@bp.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    rec = lookup.get_reservation(reservation_id)

    # State precondition.
    if rec["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "reservation is not QUOTED")

    member = db.members[rec["member_id"]]

    # Priority 8: member not blocked (no_show_strikes >= limit).
    strikes = serialize.member_no_show_strikes(rec["member_id"])
    if member.get("_strikes_override") is not None:
        strikes = member["_strikes_override"]
    if strikes >= calc.NO_SHOW_STRIKE_LIMIT:
        raise err("ERR_MEMBER_BLOCKED", "member has reached the no-show strike limit")

    # Priority 14: class availability at pickup location (available_count >= 1).
    if _available_count(rec["class_id"], rec["pickup_location_id"]) < 1:
        raise err("ERR_NO_AVAILABILITY", "no available vehicle of the reserved class")

    # Priority 21: aggregate-capacity overlap check.
    fleet_size = _fleet_size(rec["class_id"], rec["pickup_location_id"])
    overlapping = 0
    for other in db.reservations.values():
        if other["id"] == rec["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "PICKED_UP"):
            continue
        if other["pickup_location_id"] != rec["pickup_location_id"]:
            continue
        if other["class_id"] != rec["class_id"]:
            continue
        if overlaps(other, rec):
            overlapping += 1
    if overlapping >= fleet_size:
        raise err(
            "ERR_LOCATION_CLASS_CAPACITY",
            "confirming would meet or exceed the location's class fleet size",
        )

    # Apply transition + side effects.
    rec["status"] = "CONFIRMED"
    rec["quoted_total_cents"] = calc.reservation_quote(rec)
    pickup_dt = util.parse_iso8601(rec["pickup_at"])
    hold_expires = pickup_dt + timedelta(minutes=calc.NO_SHOW_GRACE_MINUTES)
    rec["hold_expires_at"] = hold_expires.strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (hold_expires.microsecond // 1000)
    )
    util.touch(rec)
    return object_response(serialize.reservation(rec), 200)


@bp.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = get_principal()
    require_roles(role, {"Member", "RentalAgent"})
    rec = lookup.get_reservation(reservation_id)
    if role == "Member" and user_id != rec["member_id"]:
        raise err("ERR_FORBIDDEN", "members may only cancel their own reservations")

    if rec["status"] not in ("QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "reservation is not QUOTED or CONFIRMED")

    # Cancelling a CONFIRMED reservation is only allowed within the grace window.
    if rec["status"] == "CONFIRMED":
        now = db.current_utc()
        hold_expires = util.parse_iso8601(rec["hold_expires_at"])
        if now > hold_expires:
            raise err("ERR_GRACE_WINDOW_EXPIRED", "cancel attempted after the grace window")
        release_held_vehicle(reservation_id)

    rec["status"] = "CANCELLED"
    util.touch(rec)
    return object_response(serialize.reservation(rec), 200)


@bp.route("/reservations/<reservation_id>/no-show", methods=["POST"])
def no_show_reservation(reservation_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    rec = lookup.get_reservation(reservation_id)

    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "reservation is not CONFIRMED")

    # No-show only strictly after the grace window.
    now = db.current_utc()
    hold_expires = util.parse_iso8601(rec["hold_expires_at"])
    if now <= hold_expires:
        raise err("ERR_WITHIN_GRACE", "no-show declared before the grace window elapsed")

    release_held_vehicle(reservation_id)
    rec["status"] = "NO_SHOW"
    util.touch(rec)
    # no_show_strikes recomputed by deriving from NO_SHOW reservations; if the
    # member's strikes were pinned, this real NO_SHOW now counts on top.
    member = db.members.get(rec["member_id"])
    if member is not None and member.get("_strikes_override") is not None:
        member["_strikes_override"] += 1
        util.touch(member)
    return object_response(serialize.reservation(rec), 200)


@bp.route("/reservations/<reservation_id>/expire", methods=["POST"])
def expire_reservation(reservation_id):
    _, role = get_principal()
    require_roles(role, {"RentalAgent"})
    rec = lookup.get_reservation(reservation_id)

    if rec["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "reservation is not QUOTED")

    rec["status"] = "EXPIRED"
    util.touch(rec)
    return object_response(serialize.reservation(rec), 200)
