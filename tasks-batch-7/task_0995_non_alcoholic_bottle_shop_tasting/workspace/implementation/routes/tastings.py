"""TastingEvent, FlightItem, and TastingSeat endpoints."""
from datetime import datetime, timezone

from flask import Blueprint

import clock
import db as _db
from db import db, new_entity, touch
from errors import (ApiError, duplicate, invalid_request, invalid_state,
                    not_found, stale_version, unauthorized)
from helpers import (age_on, body, get_or_404, opt_int, paginate,
                     pagination_params, public, req_dt, req_int, req_str)
from middleware import require, require_member_ownership
from response import success
from services import (LOYALTY_MULTIPLIER, compute_age_neutral_class,
                      event_view, fefo_allocate, fefo_check,
                      recompute_compliance_hold, recompute_on_hand,
                      restore_event_reservations, round_half_up, seats_booked,
                      sku_prohibited_in_state, SHOP_HOME_STATE, _parse_iso)

bp = Blueprint("tastings", __name__)

READ_ROLES = ["PlatformAdmin", "ShopStaff", "Member", "Anonymous"]


# ---------------------------------------------------------------------------
# Tasting events
# ---------------------------------------------------------------------------

@bp.post("/tasting-events")
def create_event():
    require(["ShopStaff", "PlatformAdmin"])
    data = body()
    host_id = data.get("host_member_id")
    if host_id is not None and isinstance(host_id, str):
        get_or_404(db["members"], host_id)
    title = req_str(data, "title")
    host_id = req_str(data, "host_member_id")
    get_or_404(db["members"], host_id)
    starts_dt, starts_raw = req_dt(data, "starts_at")
    ends_dt, ends_raw = req_dt(data, "ends_at")
    capacity = req_int(data, "capacity", min_v=1)
    price = req_int(data, "flight_price_cents", min_v=0)
    min_age = opt_int(data, "min_attendee_age_years", 0, min_v=0)
    if ends_dt <= starts_dt:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "ends_at must be strictly after starts_at")
    ent = new_entity({
        "title": title,
        "host_member_id": host_id,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "capacity": capacity,
        "status": "DRAFT",
        "flight_price_cents": price,
        "min_attendee_age_years": min_age,
        "compliance_hold": False,
        "_reserved_lots": [],
    })
    db["tasting_events"][ent["id"]] = ent
    return success(event_view(ent), status=201)


@bp.get("/tasting-events")
def list_events():
    require(READ_ROLES)
    from flask import request
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = list(db["tasting_events"].values())
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, pg = paginate(items, limit, offset)
    return success([event_view(e) for e in page], response_type="array",
                   pagination=pg)


@bp.get("/tasting-events/<eid>")
def get_event(eid):
    require(READ_ROLES)
    ent = get_or_404(db["tasting_events"], eid)
    return success(event_view(ent))


@bp.get("/tasting-events/<eid>/flight-items")
def list_flight_items(eid):
    require(READ_ROLES)
    get_or_404(db["tasting_events"], eid)
    limit, offset = pagination_params()
    items = [f for f in db["flight_items"].values()
             if f["tasting_event_id"] == eid]
    page, pg = paginate(items, limit, offset)
    return success([public(f) for f in page], response_type="array",
                   pagination=pg)


@bp.get("/tasting-events/<eid>/seats")
def list_seats(eid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    get_or_404(db["tasting_events"], eid)
    limit, offset = pagination_params()
    items = [s for s in db["tasting_seats"].values()
             if s["tasting_event_id"] == eid]
    if role == "Member":
        items = [s for s in items if s["member_id"] == uid]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


@bp.post("/tasting-events/<eid>/flight-items")
def add_flight_item(eid):
    require(["ShopStaff"])
    event = get_or_404(db["tasting_events"], eid)
    data = body()
    sku_id = data.get("sku_id")
    if sku_id is not None and isinstance(sku_id, str):
        get_or_404(db["skus"], sku_id)
    sku_id = req_str(data, "sku_id")
    sku = get_or_404(db["skus"], sku_id)
    pour = req_int(data, "pour_size_ml", min_v=5, max_v=60)
    seq = req_int(data, "sequence_no", min_v=1)
    # state: flight items only while DRAFT
    if event["status"] != "DRAFT":
        raise invalid_state("Flight items may only be added while DRAFT")
    for item in db["flight_items"].values():
        if item["tasting_event_id"] == eid and item["sequence_no"] == seq:
            raise duplicate("sequence_no already used within this event")
    if sku["discontinued"]:
        raise ApiError("ERR_SKU_DISCONTINUED", 422,
                       "Discontinued SKU cannot be added as a flight item")
    est = pour * event["capacity"] / 750.0
    ent = new_entity({
        "tasting_event_id": eid,
        "sku_id": sku_id,
        "pour_size_ml": pour,
        "sequence_no": seq,
        "estimated_bottle_consumption": est,
    })
    db["flight_items"][ent["id"]] = ent
    recompute_compliance_hold(event)
    touch(event)
    return success(public(ent), status=201)


@bp.post("/tasting-events/<eid>/publish")
def publish_event(eid):
    require(["ShopStaff"])
    event = get_or_404(db["tasting_events"], eid)
    if event["status"] != "DRAFT":
        raise invalid_state("Only DRAFT events may be published")
    if event.get("compliance_hold"):
        raise ApiError("ERR_COMPLIANCE_HOLD", 422,
                       "Event is under compliance hold")
    items = [f for f in db["flight_items"].values()
             if f["tasting_event_id"] == eid]
    if not items:
        raise invalid_request("Event requires at least one flight item")
    if _parse_iso(event["starts_at"]) <= clock.now():
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "starts_at must be in the future")
    # Inventory sufficiency across all items before mutating (atomicity).
    demands = {}
    for item in items:
        bottles = item["estimated_bottle_consumption"]
        whole = int(bottles) if float(bottles).is_integer() else int(bottles) + 1
        demands[item["sku_id"]] = demands.get(item["sku_id"], 0) + whole
    for sku_id, qty in demands.items():
        if not fefo_check(sku_id, qty):
            raise ApiError("ERR_INSUFFICIENT_INVENTORY", 422,
                           "FEFO lot walk cannot satisfy demand")
    reserved = event.get("_reserved_lots") or []
    affected = set()
    for sku_id, qty in demands.items():
        for entry in fefo_allocate(sku_id, qty):
            reserved.append((entry["lot_id"], entry["qty_taken"]))
        affected.add(sku_id)
    event["_reserved_lots"] = reserved
    event["status"] = "PUBLISHED"
    touch(event)
    for sku_id in affected:
        recompute_on_hand(sku_id)
    return success(event_view(event))


@bp.post("/tasting-events/<eid>/cancel")
def cancel_event(eid):
    require(["ShopStaff"])
    event = get_or_404(db["tasting_events"], eid)
    if event["status"] != "PUBLISHED":
        raise invalid_state("Only PUBLISHED events may be cancelled")
    for seat in db["tasting_seats"].values():
        if (seat["tasting_event_id"] == eid
                and seat["status"] in ("RESERVED", "CONFIRMED")):
            was_confirmed = seat["status"] == "CONFIRMED"
            seat["status"] = "CANCELLED"
            seat["_cancel_credited"] = False
            if was_confirmed:
                member = db["members"].get(seat["member_id"])
                if member is not None:
                    member["wallet_credit_cents"] += seat["price_paid_cents"]
                    touch(member)
                seat["_cancel_credited"] = True
            touch(seat)
    restore_event_reservations(event)
    event["status"] = "CANCELLED"
    touch(event)
    return success(event_view(event))


@bp.post("/tasting-events/<eid>/reschedule")
def reschedule_event(eid):
    require(["ShopStaff"])
    event = get_or_404(db["tasting_events"], eid)
    data = body()
    new_starts, new_starts_raw = req_dt(data, "new_starts_at")
    new_ends, new_ends_raw = req_dt(data, "new_ends_at")
    if event["status"] != "LOCKED":
        raise invalid_state("Only LOCKED events may be rescheduled")
    if new_ends <= new_starts:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "new_ends_at must be strictly after new_starts_at")
    if new_starts <= clock.now():
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "new_starts_at must be strictly in the future")
    event["starts_at"] = new_starts_raw
    event["ends_at"] = new_ends_raw
    event["status"] = "RESCHEDULED"
    touch(event)
    # System: reschedule completes -> back to PUBLISHED
    event["status"] = "PUBLISHED"
    touch(event)
    return success(event_view(event))


# ---------------------------------------------------------------------------
# Tasting seats
# ---------------------------------------------------------------------------

@bp.post("/tasting-events/<eid>/seats")
def book_seat(eid):
    role, uid = require(["Member", "ShopStaff"])
    event = get_or_404(db["tasting_events"], eid)
    data = body()
    member_id = data.get("member_id")
    if member_id is not None and isinstance(member_id, str):
        get_or_404(db["members"], member_id)
    member_id = req_str(data, "member_id")
    member = get_or_404(db["members"], member_id)
    if role == "Member" and uid != member_id:
        raise unauthorized("Member may only book own seat")
    expected = data.get("expected_event_version")
    # age attestation (priority 6)
    for item in db["flight_items"].values():
        if item["tasting_event_id"] != eid:
            continue
        sku = db["skus"].get(item["sku_id"])
        if sku is not None and sku["age_neutral_class"] == "ADULT_ONLY_REQUIRED":
            if member["age_attestation_status"] != "ATTESTED":
                raise ApiError("ERR_AGE_ATTESTATION_REQUIRED", 422,
                               "Member must be ATTESTED for this event")
    # booking window (priority 10)
    if event["status"] not in ("PUBLISHED", "RESCHEDULED"):
        raise ApiError("ERR_BOOKING_WINDOW_CLOSED", 422,
                       "Event is not bookable in its current status")
    # capacity (priority 11)
    if seats_booked(eid) >= event["capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                       "Event capacity exhausted")
    # OCC (priority 19)
    if expected is not None and expected != event["version"]:
        raise stale_version()
    ent = new_entity({
        "tasting_event_id": eid,
        "member_id": member_id,
        "status": "RESERVED",
        "price_paid_cents": event["flight_price_cents"],
        "booked_at": _db.now_ts(),
        "loyalty_points_awarded": 0,
        "_cancel_credited": False,
    })
    db["tasting_seats"][ent["id"]] = ent
    touch(event)  # seats_booked advanced; bump parent version
    return success(public(ent), status=201)


def _get_seat(sid):
    return get_or_404(db["tasting_seats"], sid)


@bp.get("/tasting-seats/<sid>")
def get_seat(sid):
    role, uid = require(["PlatformAdmin", "ShopStaff", "Member"])
    seat = _get_seat(sid)
    require_member_ownership(role, uid, seat["member_id"])
    return success(public(seat))


@bp.post("/tasting-seats/<sid>/confirm")
def confirm_seat(sid):
    role, uid = require(["Member", "ShopStaff"])
    seat = _get_seat(sid)
    if role == "Member" and uid != seat["member_id"]:
        raise unauthorized("Member may only confirm own seat")
    if seat["status"] != "RESERVED":
        raise invalid_state("Seat is not RESERVED")
    event = get_or_404(db["tasting_events"], seat["tasting_event_id"])
    member = get_or_404(db["members"], seat["member_id"])
    # age attestation (priority 6)
    for item in db["flight_items"].values():
        if item["tasting_event_id"] != event["id"]:
            continue
        sku = db["skus"].get(item["sku_id"])
        if sku is not None and sku["age_neutral_class"] == "ADULT_ONLY_REQUIRED":
            if member["age_attestation_status"] != "ATTESTED":
                raise ApiError("ERR_AGE_ATTESTATION_REQUIRED", 422,
                               "Member must be ATTESTED for this event")
    # booking window (priority 10)
    if event["status"] not in ("PUBLISHED", "RESCHEDULED"):
        raise ApiError("ERR_BOOKING_WINDOW_CLOSED", 422,
                       "Event is not bookable in its current status")
    # capacity was already enforced at booking time; this RESERVED seat already
    # occupies a counted slot, so confirming it cannot exceed capacity.
    # age requirement at event date
    starts = _parse_iso(event["starts_at"])
    if age_on(member["date_of_birth"], starts) < event["min_attendee_age_years"]:
        raise invalid_state("Member does not meet minimum attendee age")
    seat["status"] = "CONFIRMED"
    touch(seat)
    touch(event)
    return success(public(seat))


@bp.post("/tasting-seats/<sid>/cancel")
def cancel_seat(sid):
    role, uid = require(["Member", "ShopStaff"])
    seat = _get_seat(sid)
    if role == "Member" and uid != seat["member_id"]:
        raise unauthorized("Member may only cancel own seat")
    if seat["status"] not in ("RESERVED", "CONFIRMED"):
        raise invalid_state("Seat is not in a cancellable state")
    event = get_or_404(db["tasting_events"], seat["tasting_event_id"])
    if event["status"] in ("IN_SESSION", "COMPLETED"):
        raise invalid_state("Event status does not permit seat cancellation")
    was_confirmed = seat["status"] == "CONFIRMED"
    seat["status"] = "CANCELLED"
    seat["_cancel_credited"] = False
    if was_confirmed:
        member = db["members"].get(seat["member_id"])
        if member is not None:
            member["wallet_credit_cents"] += seat["price_paid_cents"]
            touch(member)
        seat["_cancel_credited"] = True
    touch(seat)
    touch(event)
    return success(public(seat))


@bp.post("/tasting-seats/<sid>/check-in")
def checkin_seat(sid):
    require(["ShopStaff"])
    seat = _get_seat(sid)
    if seat["status"] != "CONFIRMED":
        raise invalid_state("Seat is not CONFIRMED")
    event = get_or_404(db["tasting_events"], seat["tasting_event_id"])
    if event["status"] != "IN_SESSION":
        raise invalid_state("Event is not IN_SESSION")
    member = get_or_404(db["members"], seat["member_id"])
    base_pts = seat["price_paid_cents"] // 100
    mult = LOYALTY_MULTIPLIER.get(member["loyalty_tier"], 1.0)
    award = round_half_up(base_pts * mult)
    seat["loyalty_points_awarded"] = award
    seat["status"] = "ATTENDED"
    touch(seat)
    if award:
        from services import credit_loyalty
        credit_loyalty(member, award)
    return success(public(seat))


@bp.post("/tasting-seats/<sid>/refund")
def refund_seat(sid):
    require(["ShopStaff"])
    seat = _get_seat(sid)
    if seat["status"] != "CANCELLED":
        raise invalid_state("Seat is not CANCELLED")
    if not seat.get("_cancel_credited"):
        member = db["members"].get(seat["member_id"])
        if member is not None:
            member["wallet_credit_cents"] += seat["price_paid_cents"]
            touch(member)
        seat["_cancel_credited"] = True
    seat["status"] = "REFUNDED"
    touch(seat)
    return success(public(seat))
