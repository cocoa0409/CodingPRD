"""HotelBlock and RoomBooking endpoints (PRD §3.3)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, now, parse_date, touch
from errors import (ApiError, ERR_BLOCK_INVENTORY_EXCEEDED, ERR_BLOCK_NOT_CONTRACTED,
                    ERR_BLOCK_NOT_RECONCILABLE, ERR_BOOKING_OUTSIDE_BLOCK_DATES,
                    ERR_CROSS_EVENT_REFERENCE, ERR_CUTOFF_PASSED, ERR_STALE_VERSION,
                    ERR_VALIDATION, already_terminal, invalid_state,
                    posture_forbids, raise_err)
from listing import list_response
from middleware import (forbid, get_body, opt_int, opt_number, opt_str, req_enum,
                        req_int, req_number, req_str, require_any_authenticated,
                        require_roles)
from response import ok

bp = Blueprint("hotels", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Hotel blocks
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/hotel-blocks")
def create_block(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    hotel_name = req_str(data, "hotel_name")
    rooms = req_int(data, "contracted_rooms_per_night", lo=1)
    rate = req_int(data, "room_rate_cents", lo=1)
    try:
        b_start = parse_date(data.get("block_start_date"))
        b_end = parse_date(data.get("block_end_date"))
        cutoff = parse_date(data.get("cutoff_date"))
    except Exception:
        raise ApiError(*ERR_VALIDATION,
                       "block_start_date, block_end_date and cutoff_date must be ISO dates.")
    if b_end <= b_start:
        raise ApiError(*ERR_VALIDATION, "block_end_date must be strictly after block_start_date.")
    attrition = req_number(data, "attrition_allowance_pct", lo=0, hi=0.5)
    b = base_entity()
    b.update({
        "event_id": e["id"],
        "hotel_name": hotel_name,
        "contracted_rooms_per_night": rooms,
        "room_rate_cents": rate,
        "block_start_date": data.get("block_start_date"),
        "block_end_date": data.get("block_end_date"),
        "cutoff_date": data.get("cutoff_date"),
        "attrition_allowance_pct": attrition,
        "status": "NEGOTIATING",
        "final_rebate_cents": None,
        "attrition_penalty_cents": None,
        "_frozen_tier": None,
    })
    STORE.hotel_blocks[b["id"]] = b
    return ok(svc.ser_block(b), status=201)


@bp.get("/events/<id>/hotel-blocks")
def list_blocks(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.blocks_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return list_response(items, svc.ser_block)


@bp.get("/hotel-blocks/<id>")
def get_block(id):
    require_any_authenticated()
    b = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    return ok(svc.ser_block(b))


@bp.patch("/hotel-blocks/<id>")
def patch_block(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    data = get_body()
    expected = req_int(data, "expected_hotel_block_version")
    rooms = opt_int(data, "contracted_rooms_per_night", lo=1)
    rate = opt_int(data, "room_rate_cents", lo=1)
    attrition = opt_number(data, "attrition_allowance_pct", lo=0, hi=0.5)
    cutoff = None
    if "cutoff_date" in data and data["cutoff_date"] is not None:
        try:
            cutoff = parse_date(data["cutoff_date"])
        except Exception:
            raise ApiError(*ERR_VALIDATION, "cutoff_date must be an ISO date.")
    if expected != b["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_hotel_block_version does not match the block's current version.")
    if b["status"] != "NEGOTIATING":
        raise_err(ERR_BLOCK_NOT_CONTRACTED,
                  "Only a NEGOTIATING hotel block's terms can be edited.")
    if rooms is not None:
        b["contracted_rooms_per_night"] = rooms
    if rate is not None:
        b["room_rate_cents"] = rate  # existing bookings keep their pinned rate
    if cutoff is not None:
        b["cutoff_date"] = data["cutoff_date"]
    if attrition is not None:
        b["attrition_allowance_pct"] = attrition
    touch(b)
    return ok(svc.ser_block(b))


@bp.post("/hotel-blocks/<id>/contract")
def contract_block(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    e = svc.get_or_404(STORE.events, b["event_id"], "event")
    if e["posture"] not in ("BIDDING", "AWARDED", "PLANNING"):
        posture_forbids("Hotel-block contracting requires BIDDING, AWARDED, or PLANNING posture.")
    if b["status"] in svc.BLOCK_TERMINAL:
        already_terminal("hotel block")
    if b["status"] != "NEGOTIATING":
        invalid_state("Only a NEGOTIATING hotel block can be contracted.")
    b["status"] = "CONTRACTED"
    touch(b)
    return ok(svc.ser_block(b))


@bp.post("/hotel-blocks/<id>/close-cutoff")
def close_cutoff(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    if b["status"] in svc.BLOCK_TERMINAL:
        already_terminal("hotel block")
    if b["status"] != "CONTRACTED":
        invalid_state("Only a CONTRACTED hotel block's booking window can be closed.")
    if now().date() <= parse_date(b["cutoff_date"]):
        raise_err(ERR_CUTOFF_PASSED, "The cutoff date has not yet passed.")
    b["status"] = "CUTOFF_PASSED"
    touch(b)
    return ok(svc.ser_block(b))


@bp.post("/hotel-blocks/<id>/reconcile")
def reconcile_block(id):
    uid, role = require_roles("CommissionAdmin", "HotelManager")
    b = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    if role == "HotelManager":
        forbid(uid != b["id"], "HotelManager may reconcile only their own block.")
    if b["status"] in svc.BLOCK_TERMINAL:
        already_terminal("hotel block")
    if b["status"] != "CUTOFF_PASSED":
        raise_err(ERR_BLOCK_NOT_RECONCILABLE,
                  "Only a CUTOFF_PASSED hotel block can be reconciled.")
    # Final variant: actualized pickup set {CHECKED_OUT, NO_SHOW}; frozen.
    _picked, _pct, tier, rebate, penalty = svc.rebate_computation(b, svc.PICKUP_FINAL)
    b["final_rebate_cents"] = rebate
    b["attrition_penalty_cents"] = penalty
    b["_frozen_tier"] = tier
    b["status"] = "RECONCILED"
    touch(b)
    return ok(svc.ser_block(b))


# ---------------------------------------------------------------------------
# Room bookings
# ---------------------------------------------------------------------------

def _per_night_inventory_ok(block, rooms_count, ci, co):
    nights = (co - ci).days
    for i in range(nights):
        day = ci + timedelta(days=i)
        used = 0
        for bk in svc.bookings_of_block(block["id"]):
            if bk["status"] == "CANCELLED":
                continue
            bci = parse_date(bk["check_in_date"])
            bco = parse_date(bk["check_out_date"])
            if bci <= day < bco:
                used += bk["rooms_count"]
        if used + rooms_count > block["contracted_rooms_per_night"]:
            return False
    return True


@bp.post("/hotel-blocks/<id>/room-bookings")
def create_booking(id):
    uid, role = require_roles("CommissionAdmin", "TeamRep", "Official")
    block = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    data = get_body()
    booker_type = data.get("booker_type")
    # Entity-backed ownership scope (priority 2).
    if role == "TeamRep":
        forbid(booker_type != "TEAM" or data.get("team_id") != uid,
               "TeamRep may book only for their own team.")
    elif role == "Official":
        forbid(booker_type != "OFFICIAL" or data.get("official_id") != uid,
               "Officials may book only for themselves.")
    booker_type = req_enum(data, "booker_type", svc.BOOKER_TYPES)
    guest_name = req_str(data, "guest_name")
    rooms_count = req_int(data, "rooms_count", lo=1)
    team_id = data.get("team_id")
    official_id = data.get("official_id")
    if booker_type == "TEAM":
        if not isinstance(team_id, str):
            raise ApiError(*ERR_VALIDATION, "team_id is required when booker_type is TEAM.")
        official_id = None
    elif booker_type == "OFFICIAL":
        if not isinstance(official_id, str):
            raise ApiError(*ERR_VALIDATION, "official_id is required when booker_type is OFFICIAL.")
        team_id = None
    else:
        team_id = None
        official_id = None
    try:
        ci = parse_date(data.get("check_in_date"))
        co = parse_date(data.get("check_out_date"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "check_in_date and check_out_date must be ISO dates.")
    if co <= ci:
        raise ApiError(*ERR_VALIDATION, "check_out_date must be strictly after check_in_date.")
    team = None
    official = None
    if team_id is not None:
        team = svc.get_or_404(STORE.teams, team_id, "team")
    if official_id is not None:
        official = svc.get_or_404(STORE.officials, official_id, "official")
    # State gates.
    if block["status"] in svc.BLOCK_TERMINAL:
        already_terminal("hotel block")
    if block["status"] != "CONTRACTED":
        raise_err(ERR_BLOCK_NOT_CONTRACTED,
                  "Room bookings may be created only on a CONTRACTED hotel block.")
    # Temporal gates.
    if now().date() > parse_date(block["cutoff_date"]):
        raise_err(ERR_CUTOFF_PASSED, "The booking cutoff date has passed.")
    b_start = parse_date(block["block_start_date"])
    b_end = parse_date(block["block_end_date"])
    if ci < b_start or co > b_end:
        raise_err(ERR_BOOKING_OUTSIDE_BLOCK_DATES,
                  "Booking nights must lie within the block window.")
    # Cross-event referential integrity.
    if team is not None:
        t_ev = svc.event_of_team(team)
        if t_ev is None or t_ev["id"] != block["event_id"]:
            raise_err(ERR_CROSS_EVENT_REFERENCE, "The booking team belongs to a different event.")
    if official is not None:
        if official["event_id"] != block["event_id"]:
            raise_err(ERR_CROSS_EVENT_REFERENCE, "The booking official belongs to a different event.")
    # Fiscal: per-night inventory.
    if not _per_night_inventory_ok(block, rooms_count, ci, co):
        raise_err(ERR_BLOCK_INVENTORY_EXCEEDED,
                  "Per-night occupancy would exceed contracted_rooms_per_night.")
    nights = (co - ci).days
    bk = base_entity()
    bk.update({
        "hotel_block_id": block["id"],
        "booker_type": booker_type,
        "team_id": team_id,
        "official_id": official_id,
        "guest_name": guest_name,
        "rooms_count": rooms_count,
        "check_in_date": data.get("check_in_date"),
        "check_out_date": data.get("check_out_date"),
        "rate_cents": block["room_rate_cents"],  # pinned at creation
        "room_nights": rooms_count * nights,
        "total_charge_cents": rooms_count * nights * block["room_rate_cents"],
        "cancellation_fee_cents": 0,
        "status": "RESERVED",
    })
    STORE.room_bookings[bk["id"]] = bk
    return ok(svc.ser_booking(bk), status=201)


@bp.get("/hotel-blocks/<id>/room-bookings")
def list_block_bookings(id):
    require_any_authenticated()
    block = svc.get_or_404(STORE.hotel_blocks, id, "hotel block")
    items = svc.bookings_of_block(block["id"])
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["check_in_date"], b["created_at"], b["_seq"]))
    return list_response(items, svc.ser_booking)


@bp.get("/room-bookings/<id>")
def get_booking(id):
    require_any_authenticated()
    bk = svc.get_or_404(STORE.room_bookings, id, "room booking")
    return ok(svc.ser_booking(bk))


@bp.get("/room-bookings")
def list_bookings():
    require_any_authenticated()
    items = list(STORE.room_bookings.values())
    for param in ("hotel_block_id", "team_id", "official_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if b.get(param) == v]
    items.sort(key=lambda b: (b["check_in_date"], b["created_at"], b["_seq"]))
    return list_response(items, svc.ser_booking)


@bp.post("/room-bookings/<id>/transition")
def transition_booking(id):
    uid, role = require_roles("CommissionAdmin", "HotelManager", "TeamRep", "Official")
    data = get_body()
    action = data.get("action")
    # Action-level role permission (priority 2, no entity needed).
    if role in ("TeamRep", "Official"):
        forbid(action != "CANCEL", f"Role {role} may only cancel a booking.")
    action = req_enum(data, "action", svc.BOOKING_ACTIONS)
    bk = svc.get_or_404(STORE.room_bookings, id, "room booking")
    block = svc.get_or_404(STORE.hotel_blocks, bk["hotel_block_id"], "hotel block")
    # Ownership scope.
    if role == "HotelManager":
        forbid(uid != block["id"], "HotelManager may operate only their own block.")
    elif role == "TeamRep":
        forbid(bk["booker_type"] != "TEAM" or bk["team_id"] != uid,
               "TeamRep may cancel only their own team's bookings.")
    elif role == "Official":
        forbid(bk["booker_type"] != "OFFICIAL" or bk["official_id"] != uid,
               "Officials may cancel only their own bookings.")
    if bk["status"] in svc.BOOKING_TERMINAL:
        already_terminal("room booking")

    if action == "CONFIRM":
        if bk["status"] != "RESERVED":
            invalid_state("Only a RESERVED booking can be confirmed.")
        if block["status"] != "CONTRACTED":
            raise_err(ERR_BLOCK_NOT_CONTRACTED,
                      "The parent block must be CONTRACTED to confirm a booking.")
        bk["status"] = "CONFIRMED"
    elif action == "CHECK_IN":
        if bk["status"] != "CONFIRMED":
            invalid_state("Only a CONFIRMED booking can be checked in.")
        if now().date() < parse_date(bk["check_in_date"]):
            raise ApiError(*ERR_VALIDATION, "Check-in is not allowed before check_in_date.")
        bk["status"] = "CHECKED_IN"
    elif action == "CHECK_OUT":
        if bk["status"] != "CHECKED_IN":
            invalid_state("Only a CHECKED_IN booking can be checked out.")
        bk["status"] = "CHECKED_OUT"
    elif action == "CANCEL":
        if bk["status"] not in ("RESERVED", "CONFIRMED"):
            invalid_state("Only a RESERVED or CONFIRMED booking can be cancelled.")
        if now().date() <= parse_date(block["cutoff_date"]):
            bk["cancellation_fee_cents"] = 0
        else:
            bk["cancellation_fee_cents"] = svc._cents(
                Decimal(bk["rooms_count"]) * Decimal(bk["rate_cents"]) * svc.CANCEL_FEE_RATE)
        bk["status"] = "CANCELLED"  # pickup drops (recomputed live, CANCELLED excluded)
    elif action == "NO_SHOW":
        if bk["status"] != "CONFIRMED":
            invalid_state("Only a CONFIRMED booking can be marked NO_SHOW.")
        if now().date() <= parse_date(bk["check_in_date"]):
            raise ApiError(*ERR_VALIDATION, "No-show requires the clock date to be after check_in_date.")
        bk["status"] = "NO_SHOW"  # room_nights still count toward pickup
    touch(bk)
    return ok(svc.ser_booking(bk))
