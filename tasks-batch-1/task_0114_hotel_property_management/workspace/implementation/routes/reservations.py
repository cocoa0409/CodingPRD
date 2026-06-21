"""Reservation lifecycle + folio creation, assignment, upgrade, check-in/out,
cancel (PRD §3.3, §3.5, §3.6, §3.7).
"""
from flask import Blueprint

import calc
import db
import helpers as H
import serialize as S
from errors import err
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("reservations", __name__)

ALL_ROLES = {"RevenueManager", "FrontDeskAgent", "NightAuditor", "Guest"}


def _posture_open_or_raise(hotel):
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")


def _guest_owns_or_raise(role, user_id, reservation):
    if role == "Guest" and reservation["guest_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Guest may only act on their own reservation")


# ----------------------------------------------------------------------------
# Create reservation (HELD) — PRD §3.3
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations", methods=["POST"])
def create_reservation():
    user_id, role = authenticate()
    require_role(role, {"FrontDeskAgent", "Guest"})
    body = H.get_json_body()

    # body FK existence (priority 4) before body well-formedness of non-FK fields.
    H.require_fields(body, ["hotel_id", "guest_id", "room_type_id", "rate_plan_id", "arrival_date", "departure_date"])
    hotel = H.resolve_fk(body, "hotel_id")
    guest = H.resolve_fk(body, "guest_id")
    room_type = H.resolve_fk(body, "room_type_id")
    rate_plan = H.resolve_fk(body, "rate_plan_id")
    group_block = H.resolve_fk(body, "group_block_id", optional=True)

    # Guest may only book for themselves (PRD §2.1) — authorization scope.
    if role == "Guest" and guest["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Guest may only book for themselves")

    # body well-formedness (priority 5)
    arrival_date = H.require_date(body, "arrival_date")
    departure_date = H.require_date(body, "departure_date")
    if calc.parse_date(departure_date) <= calc.parse_date(arrival_date):
        raise err("ERR_INVALID_REQUEST", "departure_date must be strictly after arrival_date")
    nights = calc.nights_between(arrival_date, departure_date)

    expected_block_version = body.get("expected_group_block_version")
    if group_block is not None:
        if expected_block_version is None:
            raise err("ERR_INVALID_REQUEST", "expected_group_block_version required for a group pickup")
        if isinstance(expected_block_version, bool) or not isinstance(expected_block_version, int):
            raise err("ERR_INVALID_REQUEST", "expected_group_block_version must be an integer")

    # posture (priority 6)
    _posture_open_or_raise(hotel)

    # rate-plan applicability (priority 8): rate plan ACTIVE; group pickup plan match
    if rate_plan["status"] != "ACTIVE":
        raise err("ERR_RATE_PLAN_MISMATCH", "Rate plan is not ACTIVE")
    if group_block is not None and body["rate_plan_id"] != group_block["rate_plan_id"]:
        raise err("ERR_RATE_PLAN_MISMATCH", "Group pickup rate_plan_id must equal the block's rate_plan_id")

    # group-block cutoff (priority 9)
    if group_block is not None:
        if group_block["status"] != "OPEN" or calc.parse_date(hotel["current_business_date"]) > calc.parse_date(group_block["cutoff_date"]):
            raise err("ERR_BLOCK_CUTOFF_PASSED", "Group block pickup attempted after cutoff")

    # availability (priority 11): every night in [arrival, departure)
    d = calc.parse_date(arrival_date)
    end = calc.parse_date(departure_date)
    sellable = calc.sellable_count(hotel, room_type)
    while d < end:
        stay_date = d.isoformat()
        sold = calc.sold_count(room_type["id"], stay_date)
        if sold + 1 > sellable:
            raise err("ERR_NO_AVAILABILITY", "No availability for %s" % stay_date)
        d = calc.parse_date(stay_date)
        from datetime import timedelta
        d = d + timedelta(days=1)

    # OCC stale-block check (priority 13, last)
    if group_block is not None and expected_block_version != group_block["version"]:
        raise err("ERR_STALE_BLOCK_VERSION", "expected_group_block_version does not match")

    # corporate_account_id copied from rate plan when CORPORATE
    corporate_account_id = rate_plan["corporate_account_id"] if rate_plan["kind"] == "CORPORATE" else None

    rv = {
        "hotel_id": body["hotel_id"],
        "guest_id": body["guest_id"],
        "room_type_id": body["room_type_id"],
        "rate_plan_id": body["rate_plan_id"],
        "corporate_account_id": corporate_account_id,
        "group_block_id": body.get("group_block_id"),
        "assigned_room_id": None,
        "effective_room_type_id": body["room_type_id"],
        "arrival_date": arrival_date,
        "departure_date": departure_date,
        "nights": nights,
        "is_upgraded": False,
        "upgrade_is_comp": False,
        "status": "HELD",
    }
    db.stamp_create(rv)
    db.reservations[rv["id"]] = rv

    # Create the Folio (status OPEN, bill_to derived)
    folio = {
        "hotel_id": body["hotel_id"],
        "reservation_id": rv["id"],
        "projected_charges_cents": 0,
        "bill_to": "CORPORATE" if corporate_account_id is not None else "GUEST",
        "status": "OPEN",
    }
    db.stamp_create(folio)
    db.folios[folio["id"]] = folio

    # Group pickup cascade: recompute picked_up_rooms + bump block version.
    if group_block is not None:
        db.touch(group_block)

    return success(S.reservation_out(rv), status=201)


@bp.route("/pms/reservations/<resource_id>", methods=["GET"])
def get_reservation(resource_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    rv = H.get_or_404(db.reservations, resource_id)
    _guest_owns_or_raise(role, user_id, rv)
    return success(S.reservation_out(rv), status=200)


@bp.route("/pms/reservations", methods=["GET"])
def list_reservations():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    filters = {
        "hotel_id": H.qparam("hotel_id"),
        "guest_id": H.qparam("guest_id"),
        "room_type_id": H.qparam("room_type_id"),
        "rate_plan_id": H.qparam("rate_plan_id"),
        "group_block_id": H.qparam("group_block_id"),
        "corporate_account_id": H.qparam("corporate_account_id"),
        "assigned_room_id": H.qparam("assigned_room_id"),
        "effective_room_type_id": H.qparam("effective_room_type_id"),
        "status": H.qparam("status"),
    }
    # Guest reads scoped to own data (PRD §2.1)
    if role == "Guest":
        filters["guest_id"] = user_id
    items, limit, offset, total = H.filter_and_paginate(db.reservations, S.reservation_out, filters)
    return success_list(items, limit, offset, total)


# ----------------------------------------------------------------------------
# Confirm — PRD §3.6 / §3.7
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/confirm", methods=["POST"])
def confirm_reservation(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    rv = H.get_or_404(db.reservations, resource_id)
    hotel = db.hotels[rv["hotel_id"]]

    _posture_open_or_raise(hotel)
    if rv["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Reservation is not HELD")

    rate_plan = db.rate_plans[rv["rate_plan_id"]]
    if rate_plan["status"] != "ACTIVE":
        raise err("ERR_RATE_PLAN_MISMATCH", "Rate plan is not ACTIVE")

    folio = _folio_for(rv["id"])
    projected = calc.room_charge_forward(rv, rv["effective_room_type_id"])

    if rv["corporate_account_id"] is not None:
        ca = db.corporate_accounts[rv["corporate_account_id"]]
        if ca["status"] != "ACTIVE":
            raise err("ERR_CORPORATE_SUSPENDED", "Corporate account is SUSPENDED")
        would_be = calc.corporate_outstanding(ca["id"]) + projected
        if would_be > ca["credit_limit_cents"]:
            raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Corporate credit limit exceeded")

    rv["status"] = "CONFIRMED"
    db.touch(rv)

    folio["projected_charges_cents"] = projected
    db.touch(folio)

    if rv["group_block_id"] is not None:
        db.touch(db.group_blocks[rv["group_block_id"]])

    return success(S.reservation_out(rv), status=200)


# ----------------------------------------------------------------------------
# Assign room — PRD §3.5 (OCC on room)
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/assign-room", methods=["POST"])
def assign_room(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    rv = H.get_or_404(db.reservations, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["room_id", "expected_room_version"])
    room = H.resolve_fk(body, "room_id")
    expected = H.require_int(body, "expected_room_version")

    hotel = db.hotels[rv["hotel_id"]]
    _posture_open_or_raise(hotel)

    # room assignability (priority 10): not OOO, not bound elsewhere, tier ok
    eff_type = db.room_types[rv["effective_room_type_id"]]
    target_type = db.room_types[room["room_type_id"]]
    if room["housekeeping_status"] == "OUT_OF_ORDER":
        raise err("ERR_ROOM_NOT_ASSIGNABLE", "Room is OUT_OF_ORDER")
    if room["assigned_reservation_id"] is not None and room["assigned_reservation_id"] != rv["id"]:
        raise err("ERR_ROOM_NOT_ASSIGNABLE", "Room is bound to another reservation")
    if target_type["tier_rank"] < eff_type["tier_rank"]:
        raise err("ERR_ROOM_NOT_ASSIGNABLE", "Room type tier is below the reservation's effective tier")

    # OCC last (priority 13)
    if expected != room["version"]:
        raise err("ERR_STALE_ROOM_VERSION", "expected_room_version does not match Room.version")

    rv["assigned_room_id"] = room["id"]
    db.touch(rv)
    room["assigned_reservation_id"] = rv["id"]
    db.touch(room)
    return success(S.reservation_out(rv), status=200)


# ----------------------------------------------------------------------------
# Upgrade — PRD §3.5
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/upgrade", methods=["POST"])
def upgrade_reservation(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    rv = H.get_or_404(db.reservations, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["target_room_type_id", "comp"])
    # target_room_type_id is a RoomType FK carried in the body; an unknown
    # target is a reference-not-found per PRD §2.5.
    target_type = db.room_types.get(body["target_room_type_id"])
    if target_type is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced target_room_type_id does not exist")
    comp = body["comp"]
    if not isinstance(comp, bool):
        raise err("ERR_INVALID_REQUEST", "comp must be a boolean")

    hotel = db.hotels[rv["hotel_id"]]
    _posture_open_or_raise(hotel)

    # target must be a higher tier than the reservation's current effective tier
    eff_type = db.room_types[rv["effective_room_type_id"]]
    if target_type["tier_rank"] < eff_type["tier_rank"]:
        raise err("ERR_ROOM_NOT_ASSIGNABLE", "Upgrade target tier is below the effective tier")

    rv["effective_room_type_id"] = target_type["id"]
    rv["is_upgraded"] = True
    rv["upgrade_is_comp"] = comp

    if not comp:
        folio = _folio_for(rv["id"])
        folio["projected_charges_cents"] = calc.room_charge_forward(rv, rv["effective_room_type_id"])
        db.touch(folio)

    db.touch(rv)
    return success(S.reservation_out(rv), status=200)


# ----------------------------------------------------------------------------
# Check-in — PRD §3.6
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/check-in", methods=["POST"])
def check_in(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    rv = H.get_or_404(db.reservations, resource_id)
    hotel = db.hotels[rv["hotel_id"]]

    _posture_open_or_raise(hotel)
    if rv["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Reservation is not CONFIRMED")
    if rv["assigned_room_id"] is None:
        raise err("ERR_NO_ROOM_ASSIGNED", "No room assigned")
    room = db.rooms[rv["assigned_room_id"]]
    if room["housekeeping_status"] != "INSPECTED":
        raise err("ERR_ROOM_NOT_INSPECTED", "Assigned room is not INSPECTED")
    if calc.parse_date(hotel["current_business_date"]) < calc.parse_date(rv["arrival_date"]):
        raise err("ERR_ARRIVAL_NOT_REACHED", "Arrival date not yet reached")

    rv["status"] = "CHECKED_IN"
    db.touch(rv)
    room["housekeeping_status"] = "OCCUPIED"
    db.touch(room)
    return success(S.reservation_out(rv), status=200)


# ----------------------------------------------------------------------------
# Check-out — PRD §3.6 / §3.7
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/check-out", methods=["POST"])
def check_out(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent"})
    rv = H.get_or_404(db.reservations, resource_id)
    hotel = db.hotels[rv["hotel_id"]]

    _posture_open_or_raise(hotel)
    if rv["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Reservation is not CHECKED_IN")
    folio = _folio_for(rv["id"])
    if folio["status"] == "DISPUTED":
        raise err("ERR_FOLIO_DISPUTED_CHECKOUT", "Folio is DISPUTED")

    rv["status"] = "CHECKED_OUT"
    db.touch(rv)

    folio["status"] = "CLOSED"
    db.touch(folio)

    if rv["assigned_room_id"] is not None:
        room = db.rooms[rv["assigned_room_id"]]
        room["housekeeping_status"] = "DIRTY"
        room["assigned_reservation_id"] = None
        db.touch(room)

    # Corporate ledger sync: outstanding recomputed from CHECKED_OUT folios, so
    # the account's version must still bump to reflect the ledger mutation.
    if folio["bill_to"] == "CORPORATE" and rv["corporate_account_id"] is not None:
        db.touch(db.corporate_accounts[rv["corporate_account_id"]])

    return success(S.reservation_out(rv), status=200)


# ----------------------------------------------------------------------------
# Cancel — PRD §3.3
# ----------------------------------------------------------------------------
@bp.route("/pms/reservations/<resource_id>/cancel", methods=["POST"])
def cancel_reservation(resource_id):
    user_id, role = authenticate()
    require_role(role, {"FrontDeskAgent", "Guest"})
    rv = H.get_or_404(db.reservations, resource_id)
    _guest_owns_or_raise(role, user_id, rv)
    hotel = db.hotels[rv["hotel_id"]]

    _posture_open_or_raise(hotel)
    if rv["status"] not in ("HELD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Reservation is not in a cancellable state")

    rv["status"] = "CANCELLED"
    db.touch(rv)

    if rv["assigned_room_id"] is not None:
        room = db.rooms[rv["assigned_room_id"]]
        room["assigned_reservation_id"] = None
        db.touch(room)  # housekeeping_status unchanged

    # Folio close (cascade)
    folio = _folio_for(rv["id"])
    if folio is not None and folio["status"] != "CLOSED":
        folio["status"] = "CLOSED"
        db.touch(folio)

    if rv["group_block_id"] is not None:
        db.touch(db.group_blocks[rv["group_block_id"]])

    return success(S.reservation_out(rv), status=200)


def _folio_for(reservation_id):
    for f in db.folios.values():
        if f["reservation_id"] == reservation_id:
            return f
    return None
