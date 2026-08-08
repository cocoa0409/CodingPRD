from flask import Blueprint, request

from core import (
    db, now, base_entity, touch, serialize, ok_object, ok_array, paginate,
    auth, forbid, lookup, get_body, require_str, require_enum, require_int,
    require_dt, opt_bool, ApiError,
)
from logic import compute_quoted_fee, compute_settled_fee, peak_load

bp = Blueprint("amenity", __name__)

AMENITY_TYPES = {"POOL", "GYM", "CLUBHOUSE", "TENNIS"}
RESERVATION_STATES = {"BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"}


# ---------------------------------------------------------------------------
# Amenities (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.route("/access/amenities", methods=["POST"])
def create_amenity():
    auth({"CommunityAdmin"})
    body = get_body()
    community_id = require_str(body, "community_id")
    name = require_str(body, "name")
    amenity_type = require_enum(body, "amenity_type", AMENITY_TYPES)
    capacity = require_int(body, "capacity", minimum=1)
    hourly_fee_cents = require_int(body, "hourly_fee_cents", minimum=0)
    deposit_cents = require_int(body, "deposit_cents", minimum=0)
    open_hour = require_int(body, "open_hour", minimum=0, maximum=23)
    close_hour = require_int(body, "close_hour", minimum=1, maximum=24)
    reservable = opt_bool(body, "reservable", True)
    lookup(db.communities, community_id, "ERR_COMMUNITY_NOT_FOUND")

    obj = base_entity()
    obj.update({
        "community_id": community_id,
        "name": name,
        "amenity_type": amenity_type,
        "capacity": capacity,
        "hourly_fee_cents": hourly_fee_cents,
        "deposit_cents": deposit_cents,
        "open_hour": open_hour,
        "close_hour": close_hour,
        "reservable": reservable,
    })
    db.amenities[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/amenities/<amenity_id>", methods=["GET"])
def get_amenity(amenity_id):
    auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.amenities, amenity_id, "ERR_AMENITY_NOT_FOUND")
    return ok_object(serialize(obj))


@bp.route("/access/amenities", methods=["GET"])
def list_amenities():
    auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.amenities.values())
    if args.get("community_id"):
        rows = [r for r in rows if r["community_id"] == args["community_id"]]
    if args.get("amenity_type"):
        rows = [r for r in rows if r["amenity_type"] == args["amenity_type"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Amenity reservations (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.route("/access/amenity-reservations", methods=["POST"])
def create_reservation():
    uid, role = auth({"Resident", "CommunityAdmin"})
    body = get_body()
    amenity_id = require_str(body, "amenity_id")
    resident_id = require_str(body, "resident_id")
    if role == "Resident" and resident_id != uid:
        forbid("Resident may only book own reservation")
    start_at = require_dt(body, "start_at")
    end_at = require_dt(body, "end_at")
    party_size = require_int(body, "party_size", minimum=1)
    amenity = lookup(db.amenities, amenity_id, "ERR_AMENITY_NOT_FOUND")
    resident = lookup(db.residents, resident_id, "ERR_RESIDENT_NOT_FOUND")

    # Business gates in PRD 2.10 order.
    if resident["status"] != "ACTIVE" or resident["standing"] != "GOOD":
        raise ApiError("ERR_RESIDENT_NOT_ELIGIBLE", 409, "Resident not eligible to book")
    if peak_load(amenity_id, start_at, end_at) + party_size > amenity["capacity"]:
        raise ApiError("ERR_AMENITY_AT_CAPACITY", 409, "Amenity at capacity")
    if not amenity["reservable"]:
        raise ApiError("ERR_AMENITY_NOT_RESERVABLE", 422, "Amenity not reservable")

    obj = base_entity()
    obj.update({
        "amenity_id": amenity_id,
        "resident_id": resident_id,
        "start_at": start_at,
        "end_at": end_at,
        "party_size": party_size,
        "status": "BOOKED",
        "quoted_fee_cents": compute_quoted_fee(amenity, start_at, end_at),
        "settled_fee_cents": None,
        "checkin_at": None,
        "checkout_at": None,
    })
    db.reservations[obj["id"]] = obj
    return ok_object(serialize(obj), 201)


@bp.route("/access/amenity-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    obj = lookup(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    if role == "Resident" and obj["resident_id"] != uid:
        forbid("Resident may only read own reservation")
    return ok_object(serialize(obj))


@bp.route("/access/amenity-reservations", methods=["GET"])
def list_reservations():
    uid, role = auth({"CommunityAdmin", "SecurityOfficer", "Resident"})
    args = request.args
    rows = list(db.reservations.values())
    if role == "Resident":
        rows = [r for r in rows if r["resident_id"] == uid]
    if args.get("amenity_id"):
        rows = [r for r in rows if r["amenity_id"] == args["amenity_id"]]
    if args.get("resident_id"):
        rows = [r for r in rows if r["resident_id"] == args["resident_id"]]
    if args.get("status"):
        rows = [r for r in rows if r["status"] == args["status"]]
    items, limit, offset, total = paginate(rows)
    return ok_array(items, limit, offset, total)


@bp.route("/access/amenity-reservations/<reservation_id>/transition", methods=["POST"])
def transition_reservation(reservation_id):
    uid, role = auth({"Resident", "CommunityAdmin"})
    reservation = lookup(db.reservations, reservation_id, "ERR_RESERVATION_NOT_FOUND")
    if role == "Resident" and reservation["resident_id"] != uid:
        forbid("Resident may only act on own reservation")
    body = get_body()
    to_status = require_enum(body, "to_status", RESERVATION_STATES)

    if to_status == "NO_SHOW" and role != "CommunityAdmin":
        forbid("Only CommunityAdmin may mark NO_SHOW")

    cur = reservation["status"]
    allowed = {
        "BOOKED": {"CHECKED_IN", "CANCELLED", "NO_SHOW"},
        "CHECKED_IN": {"COMPLETED"},
    }
    if to_status not in allowed.get(cur, set()):
        raise ApiError("ERR_INVALID_STATE", 409, "Transition not permitted")

    amenity = db.amenities[reservation["amenity_id"]]

    if to_status == "CHECKED_IN":
        if not (reservation["start_at"] <= now() < reservation["end_at"]):
            raise ApiError("ERR_RESERVATION_WINDOW_INVALID", 422, "Check-in outside window")
        load = peak_load(
            reservation["amenity_id"], reservation["start_at"], reservation["end_at"],
            exclude_id=reservation["id"],
        )
        if load + reservation["party_size"] > amenity["capacity"]:
            raise ApiError("ERR_AMENITY_AT_CAPACITY", 409, "Amenity at capacity")
        reservation["status"] = "CHECKED_IN"
        reservation["checkin_at"] = now()
        touch(reservation)
    elif to_status == "COMPLETED":
        reservation["checkout_at"] = now()
        reservation["settled_fee_cents"] = compute_settled_fee(amenity, reservation)
        reservation["status"] = "COMPLETED"
        touch(reservation)
    elif to_status == "CANCELLED":
        reservation["status"] = "CANCELLED"
        touch(reservation)
    elif to_status == "NO_SHOW":
        reservation["settled_fee_cents"] = amenity["deposit_cents"]
        reservation["status"] = "NO_SHOW"
        touch(reservation)

    return ok_object(serialize(reservation))
