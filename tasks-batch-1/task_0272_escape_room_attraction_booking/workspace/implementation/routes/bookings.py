from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, now_iso
from middleware import require_roles, get_identity, get_json
from response import created, ok, listing
from services import validate as V
from services.entities import (
    get_room, get_slot, get_customer, get_booking, get_gift_card,
    ser_booking, touch, gift_card_balance,
)
from services import pricing

bp = Blueprint("bookings", __name__)


def _customer_owns(user_id, role, booking):
    if role == "Customer" and user_id != booking["customer_id"]:
        raise err(errors.ERR_FORBIDDEN, "Customer does not own this booking")


def _append_gc_entry(gift_card_id, entry_type, delta_cents, related_booking_id):
    eid = new_id()
    entry = {
        "id": eid,
        "gift_card_id": gift_card_id,
        "related_booking_id": related_booking_id,
        "entry_type": entry_type,
        "delta_cents": delta_cents,
        "created_at": now_iso(),
    }
    db.gift_card_entries[eid] = entry
    return entry


# =========================================================================
# Create booking (slot grab)
# =========================================================================
@bp.post("/bookings")
def create_booking():
    user_id, role = require_roles({"Customer"})
    body = get_json()
    # Named body references first (string presence is request-shape, but the
    # values are resolved for existence before other scalar validation so a
    # named-but-missing reference yields 404 ahead of a 422 on another field —
    # PRD §2.9 existence (priority 4) precedes request-shape (priority 5)).
    time_slot_id = V.req_str(body, "time_slot_id")
    customer_id = V.req_str(body, "customer_id")

    # Ownership: customer acts as themselves.
    if user_id != customer_id:
        raise err(errors.ERR_FORBIDDEN, "Customer may only book for themselves")

    # Body-reference existence (404).
    slot = get_slot(time_slot_id)
    get_customer(customer_id)
    room = get_room(slot["room_id"])

    # Remaining request-shape validation (422).
    group_size = V.req_int(body, "group_size")
    expected_version = V.req_int(body, "expected_time_slot_version")
    is_private = V.opt_bool(body, "is_private", default=False)

    # State: slot must be OPEN.
    if slot["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "Slot is not OPEN")

    # OCC on slot version.
    if expected_version != slot["version"]:
        raise err(errors.ERR_STALE_SLOT_VERSION, "Stale slot version")

    # Room retired.
    if room["status"] == "RETIRED":
        raise err(errors.ERR_ROOM_RETIRED, "Room is retired")

    # Group-size band.
    if not (room["min_group_size"] <= group_size <= room["max_group_size"]):
        raise err(errors.ERR_GROUP_SIZE_INVALID, "group_size outside room band")

    # Room temporal overlap (buffer included).
    if pricing.room_overlap_conflict(slot, room["id"]):
        raise err(errors.ERR_SLOT_OVERLAP, "Slot overlaps another HELD/BOOKED slot of room")

    # Game master availability (buffer excluded).
    gm = pricing.select_game_master(slot["venue_id"], slot)
    if gm is None:
        raise err(errors.ERR_NO_GAMEMASTER_AVAILABLE, "No game master available")

    # --- Commit ---
    bid = new_id()
    ts = now_iso()
    booking = {
        "id": bid,
        "venue_id": slot["venue_id"],
        "room_id": room["id"],
        "time_slot_id": time_slot_id,
        "customer_id": customer_id,
        "gift_card_id": None,
        "group_size": group_size,
        "is_private": is_private,
        "quoted_charge_cents": 0,
        "final_charge_cents": 0,
        "gift_card_applied_cents": 0,
        "no_show_fee_cents": 0,
        "lifecycle_status": "DRAFT",
        "payment_status": "UNPAID",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.bookings[bid] = booking

    slot["status"] = "HELD"
    slot["booking_id"] = bid
    slot["assigned_game_master_id"] = gm["id"]
    touch(slot)
    # gm.active_assignment_count is computed on read; bump version/timestamp via touch.
    touch(gm)
    return created(ser_booking(booking))


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    booking = get_booking(booking_id)
    return ok(ser_booking(booking))


@bp.get("/bookings")
def list_bookings():
    require_roles({"PlatformAdmin", "VenueManager", "GameMaster", "Customer"})
    limit, offset = V.parse_pagination()
    customer_id = request.args.get("customer_id")
    time_slot_id = request.args.get("time_slot_id")
    gift_card_id = request.args.get("gift_card_id")
    room_id = request.args.get("room_id")
    venue_id = request.args.get("venue_id")
    lifecycle_status = request.args.get("lifecycle_status")
    rows = list(db.bookings.values())
    if customer_id is not None:
        rows = [b for b in rows if b["customer_id"] == customer_id]
    if time_slot_id is not None:
        rows = [b for b in rows if b["time_slot_id"] == time_slot_id]
    if gift_card_id is not None:
        rows = [b for b in rows if b.get("gift_card_id") == gift_card_id]
    if room_id is not None:
        rows = [b for b in rows if b["room_id"] == room_id]
    if venue_id is not None:
        rows = [b for b in rows if b["venue_id"] == venue_id]
    if lifecycle_status is not None:
        rows = [b for b in rows if b["lifecycle_status"] == lifecycle_status]
    page, total = V.paginate(rows, limit, offset)
    return listing([ser_booking(b) for b in page], limit, offset, total)


# =========================================================================
# Add participant
# =========================================================================
@bp.post("/bookings/<booking_id>/participants")
def add_participant(booking_id):
    user_id, role = require_roles({"Customer"})
    booking = get_booking(booking_id)
    _customer_owns(user_id, role, booking)
    body = get_json()
    display_name = V.req_str(body, "display_name")
    age = V.req_int(body, "age", min_v=0)
    if booking["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Booking not in DRAFT/CONFIRMED")

    ts = now_iso()
    pid = new_id()
    participant = {
        "id": pid,
        "booking_id": booking_id,
        "display_name": display_name,
        "age": age,
        "waiver_status": "PENDING",
        "checked_in": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.participants[pid] = participant
    from services.entities import ser_participant
    return created(ser_participant(participant))


# =========================================================================
# Confirm
# =========================================================================
@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    user_id, role = require_roles({"Customer"})
    booking = get_booking(booking_id)
    _customer_owns(user_id, role, booking)
    body = get_json()
    gift_card_id = V.opt_str(body, "gift_card_id", default=None)
    expected_booking_version = V.req_int(body, "expected_booking_version")

    # Body-reference existence for gift card.
    gc = None
    if gift_card_id is not None:
        gc = get_gift_card(gift_card_id)

    # State.
    if booking["lifecycle_status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Booking not in DRAFT")
    slot = get_slot(booking["time_slot_id"])
    if slot["status"] != "HELD":
        raise err(errors.ERR_INVALID_STATE, "Held slot is not HELD")

    # OCC.
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    # No-show risk gate.
    from services.entities import customer_strikes
    venue = db.venues[booking["venue_id"]]
    strikes = customer_strikes(booking["customer_id"])
    if strikes >= venue["no_show_strike_limit"]:
        raise err(errors.ERR_NO_SHOW_LIMIT_REACHED, "Customer no-show strike limit reached")

    # Gift-card usability.
    if gc is not None:
        bal = gift_card_balance(gc["id"], gc)
        if gc["status"] != "ACTIVE" or gc["venue_id"] != booking["venue_id"] or bal <= 0:
            raise err(errors.ERR_GIFT_CARD_UNUSABLE, "Gift card unusable")

    # --- Commit ---
    room = get_room(booking["room_id"])
    quoted = pricing.compute_quote(booking, room, slot)
    booking["quoted_charge_cents"] = quoted

    if gc is not None:
        bal = gift_card_balance(gc["id"], gc)
        applied = min(quoted, bal)
        booking["gift_card_id"] = gift_card_id
        booking["gift_card_applied_cents"] = applied
        _append_gc_entry(gc["id"], "SPEND", -applied, booking_id)
        new_bal = gift_card_balance(gc["id"], gc)
        if new_bal == 0:
            gc["status"] = "DEPLETED"
        touch(gc)

    booking["payment_status"] = "AUTHORIZED"
    booking["lifecycle_status"] = "CONFIRMED"
    touch(booking)

    slot["status"] = "BOOKED"
    touch(slot)
    return ok(ser_booking(booking))


# =========================================================================
# Reschedule
# =========================================================================
@bp.post("/bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    user_id, role = require_roles({"Customer"})
    booking = get_booking(booking_id)
    _customer_owns(user_id, role, booking)
    body = get_json()
    # Named body reference resolved before other scalar validation.
    new_time_slot_id = V.req_str(body, "new_time_slot_id")
    new_slot = get_slot(new_time_slot_id)
    old_slot = get_slot(booking["time_slot_id"])

    expected_time_slot_version = V.req_int(body, "expected_time_slot_version")
    expected_booking_version = V.req_int(body, "expected_booking_version")

    # State: booking CONFIRMED.
    if booking["lifecycle_status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Booking not in CONFIRMED")

    # OCC on old slot (slot-version error) then booking version (generic).
    if expected_time_slot_version != old_slot["version"]:
        raise err(errors.ERR_STALE_SLOT_VERSION, "Stale slot version")
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    # Target must be an OPEN slot of the SAME room.
    if new_slot["room_id"] != booking["room_id"]:
        raise err(errors.ERR_INVALID_STATE, "New slot is not of the same room")
    if new_slot["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "New slot is not OPEN")

    room = get_room(booking["room_id"])

    # Room overlap on new slot (exclude the old slot which is about to be freed).
    if pricing.room_overlap_conflict(new_slot, room["id"], exclude_slot_id=old_slot["id"]):
        raise err(errors.ERR_SLOT_OVERLAP, "New slot overlaps another HELD/BOOKED slot")

    # Game-master availability on new slot (exclude the old slot's assignment).
    gm = pricing.select_game_master(new_slot["venue_id"], new_slot, exclude_slot_id=old_slot["id"])
    if gm is None:
        raise err(errors.ERR_NO_GAMEMASTER_AVAILABLE, "No game master available")

    # --- Commit ---
    old_gm_id = old_slot.get("assigned_game_master_id")
    old_slot["status"] = "OPEN"
    old_slot["booking_id"] = None
    old_slot["assigned_game_master_id"] = None
    touch(old_slot)
    if old_gm_id and old_gm_id in db.game_masters:
        touch(db.game_masters[old_gm_id])

    new_slot["status"] = "BOOKED"
    new_slot["booking_id"] = booking_id
    new_slot["assigned_game_master_id"] = gm["id"]
    touch(new_slot)
    touch(gm)

    booking["time_slot_id"] = new_time_slot_id
    booking["venue_id"] = new_slot["venue_id"]
    booking["room_id"] = new_slot["room_id"]
    booking["quoted_charge_cents"] = pricing.compute_quote(booking, room, new_slot)
    touch(booking)
    return ok(ser_booking(booking))


# =========================================================================
# Check-in
# =========================================================================
@bp.post("/bookings/<booking_id>/check-in")
def check_in_booking(booking_id):
    require_roles({"GameMaster"})
    booking = get_booking(booking_id)
    body = get_json()
    expected_booking_version = V.req_int(body, "expected_booking_version")

    if booking["lifecycle_status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Booking not in CONFIRMED")
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    room = get_room(booking["room_id"])
    checked = [p for p in db.participants.values()
               if p["booking_id"] == booking_id and p["checked_in"]]

    # Priority 8: age; 9: waiver; 10: group size (per validations table order).
    for p in checked:
        if p["age"] < room["min_age"]:
            raise err(errors.ERR_AGE_REQUIREMENT_NOT_MET, "Checked-in participant under min_age")
    if room["waiver_required"]:
        for p in checked:
            if p["waiver_status"] != "SIGNED":
                raise err(errors.ERR_WAIVER_NOT_SIGNED, "Checked-in participant waiver not signed")
    if len(checked) < room["min_group_size"]:
        raise err(errors.ERR_GROUP_SIZE_INVALID, "Fewer checked-in than min_group_size")

    booking["lifecycle_status"] = "CHECKED_IN"
    touch(booking)
    return ok(ser_booking(booking))


# =========================================================================
# Complete
# =========================================================================
@bp.post("/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    require_roles({"GameMaster"})
    booking = get_booking(booking_id)
    body = get_json()
    expected_booking_version = V.req_int(body, "expected_booking_version")

    if booking["lifecycle_status"] != "CHECKED_IN":
        raise err(errors.ERR_INVALID_STATE, "Booking not in CHECKED_IN")
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    room = get_room(booking["room_id"])
    slot = get_slot(booking["time_slot_id"])
    settled_count = sum(1 for p in db.participants.values()
                        if p["booking_id"] == booking_id and p["checked_in"])
    booking["final_charge_cents"] = pricing.compute_settlement(booking, room, slot, settled_count)
    booking["payment_status"] = "CAPTURED"
    booking["lifecycle_status"] = "COMPLETED"
    touch(booking)
    return ok(ser_booking(booking))


# =========================================================================
# No-show
# =========================================================================
@bp.post("/bookings/<booking_id>/no-show")
def no_show_booking(booking_id):
    require_roles({"GameMaster"})
    booking = get_booking(booking_id)
    body = get_json()
    expected_booking_version = V.req_int(body, "expected_booking_version")

    if booking["lifecycle_status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Booking not in CONFIRMED")
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    venue = db.venues[booking["venue_id"]]
    fee = pricing.compute_no_show_fee(booking["quoted_charge_cents"], venue["no_show_fee_pct"])
    booking["no_show_fee_cents"] = fee
    booking["final_charge_cents"] = fee
    booking["payment_status"] = "CAPTURED"

    # Free the slot (frees gm via computed count); bump versions on cascade.
    slot = get_slot(booking["time_slot_id"])
    gm_id = slot.get("assigned_game_master_id")
    slot["status"] = "OPEN"
    slot["booking_id"] = None
    slot["assigned_game_master_id"] = None
    touch(slot)
    if gm_id and gm_id in db.game_masters:
        touch(db.game_masters[gm_id])

    booking["lifecycle_status"] = "NO_SHOW"
    touch(booking)
    # Customer strike count is computed on read; bump the customer record.
    cust = db.customers.get(booking["customer_id"])
    if cust is not None:
        touch(cust)
    return ok(ser_booking(booking))


# =========================================================================
# Cancel
# =========================================================================
@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = require_roles({"Customer"})
    booking = get_booking(booking_id)
    _customer_owns(user_id, role, booking)
    body = get_json()
    expected_booking_version = V.req_int(body, "expected_booking_version")

    if booking["lifecycle_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "Booking not in DRAFT/CONFIRMED")
    if expected_booking_version != booking["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    prev_payment = booking["payment_status"]

    # Refund gift card spend if one was applied.
    applied = booking.get("gift_card_applied_cents", 0)
    if applied > 0 and booking.get("gift_card_id"):
        gc = db.gift_cards.get(booking["gift_card_id"])
        if gc is not None:
            _append_gc_entry(gc["id"], "REFUND", applied, booking_id)
            new_bal = gift_card_balance(gc["id"], gc)
            if gc["status"] == "DEPLETED" and new_bal > 0:
                gc["status"] = "ACTIVE"
            touch(gc)
        booking["gift_card_applied_cents"] = 0

    if prev_payment in ("AUTHORIZED", "CAPTURED"):
        booking["payment_status"] = "REFUNDED"

    # Free held/booked slot.
    slot = db.time_slots.get(booking["time_slot_id"])
    if slot is not None and slot["status"] in ("HELD", "BOOKED"):
        gm_id = slot.get("assigned_game_master_id")
        slot["status"] = "OPEN"
        slot["booking_id"] = None
        slot["assigned_game_master_id"] = None
        touch(slot)
        if gm_id and gm_id in db.game_masters:
            touch(db.game_masters[gm_id])

    booking["lifecycle_status"] = "CANCELLED"
    touch(booking)
    return ok(ser_booking(booking))
