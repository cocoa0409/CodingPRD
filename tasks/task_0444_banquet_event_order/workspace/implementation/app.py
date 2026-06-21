"""Banquet Event Order & Catering Sales (BEO) API — Flask entry point.

In-memory storage only; state is wiped on every process start. No seeding.
"""
import os
from datetime import datetime

from flask import Flask, request

import db
import errors
import helpers
import services as svc
import validators as v
from middleware import authenticate, require_role
from response import success, list_success, error

app = Flask(__name__)
app.url_map.strict_slashes = False

ALL_ROLES = helpers.ALL_ROLES


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error(e)


@app.errorhandler(404)
def handle_404(e):
    return error(errors.not_found("No such route"))


@app.errorhandler(405)
def handle_405(e):
    return error(errors.not_found("Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return error(e)
    return error(errors.invalid_request("Unexpected error: " + str(e)))


def get_json_body():
    """Parse the JSON body. Returns {} for an empty body so action endpoints
    that take no input still work; malformed JSON -> ERR_INVALID_REQUEST."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return body


# ===========================================================================
# Logical clock (§1.5 / PRD §2.9)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    iso = v.req_str(body, "to_iso8601")
    # Validate it parses as a datetime.
    try:
        svc.parse_dt(iso)
    except Exception:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant")
    db.clock_utc = iso
    return success({"current_utc": db.clock_utc}, status=200)


# ===========================================================================
# FunctionRoom
# ===========================================================================
@app.route("/function-rooms", methods=["POST"])
def create_function_room():
    role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesManager"})
    body = v.require_body(get_json_body())
    name = v.req_str(body, "name")
    max_capacity = v.req_int(body, "max_capacity", minimum=1)
    hourly = v.req_int(body, "hourly_rental_cents", minimum=0)
    buffer_min = v.opt_int(body, "turnover_buffer_minutes", default=60, minimum=0)
    now = db.now_iso()
    rid = db.new_id()
    room = {
        "id": rid,
        "name": name,
        "max_capacity": max_capacity,
        "turnover_buffer_minutes": buffer_min,
        "hourly_rental_cents": hourly,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.function_rooms[rid] = room
    return success(svc.serialize_function_room(room), status=201)


@app.route("/function-rooms/<room_id>", methods=["GET"])
def get_function_room(room_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    room = helpers.get_function_room_or_404(room_id)
    return success(svc.serialize_function_room(room), status=200)


@app.route("/function-rooms", methods=["GET"])
def list_function_rooms():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = helpers.parse_pagination()
    status_filter = request.args.get("status")
    rows = list(db.function_rooms.values())
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_function_room)
    return list_success(items, limit, offset, total)


@app.route("/function-rooms/<room_id>/bookings", methods=["GET"])
def list_function_room_bookings(room_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_function_room_or_404(room_id)
    limit, offset = helpers.parse_pagination()
    rows = [b for b in db.bookings.values() if b["function_room_id"] == room_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_booking)
    return list_success(items, limit, offset, total)


# ===========================================================================
# HotelRoomBlock
# ===========================================================================
@app.route("/hotel-room-blocks", methods=["POST"])
def create_hotel_room_block():
    role = authenticate()
    require_role(role, {"PlatformAdmin", "SalesManager"})
    body = v.require_body(get_json_body())
    block_name = v.req_str(body, "block_name")
    total_rooms = v.req_int(body, "total_rooms", minimum=1)
    nightly = v.req_int(body, "nightly_rate_cents", minimum=0)
    now = db.now_iso()
    bid = db.new_id()
    block = {
        "id": bid,
        "block_name": block_name,
        "total_rooms": total_rooms,
        "nightly_rate_cents": nightly,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.hotel_room_blocks[bid] = block
    return success(svc.serialize_hotel_room_block(block), status=201)


@app.route("/hotel-room-blocks/<block_id>", methods=["GET"])
def get_hotel_room_block(block_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    block = helpers.get_block_or_404(block_id)
    return success(svc.serialize_hotel_room_block(block), status=200)


@app.route("/hotel-room-blocks", methods=["GET"])
def list_hotel_room_blocks():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = helpers.parse_pagination()
    rows = list(db.hotel_room_blocks.values())
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_hotel_room_block)
    return list_success(items, limit, offset, total)


@app.route("/hotel-room-blocks/<block_id>/room-block-links", methods=["GET"])
def list_block_links(block_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_block_or_404(block_id)
    limit, offset = helpers.parse_pagination()
    rows = [l for l in db.room_block_links.values() if l["hotel_room_block_id"] == block_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_room_block_link)
    return list_success(items, limit, offset, total)


# ===========================================================================
# Event lifecycle
# ===========================================================================
SETUP_STYLES = {"ROUNDS", "THEATER", "CLASSROOM", "RECEPTION"}


@app.route("/events", methods=["POST"])
def create_event():
    role = authenticate()
    require_role(role, {"SalesManager"})
    body = v.require_body(get_json_body())
    account_name = v.req_str(body, "account_name")
    event_date = v.req_str(body, "event_date")
    setup_style = v.req_enum(body, "setup_style", SETUP_STYLES)
    expected = v.req_int(body, "expected_attendance", minimum=1)
    overset = v.opt_pct(body, "overset_pct", 0.05, 0.0, 0.10)
    service_charge = v.opt_pct(body, "service_charge_pct", 0.22, 0.0, 0.30)
    gratuity = v.opt_pct(body, "gratuity_pct", 0.0, 0.0, 0.25)
    sales_tax = v.opt_pct(body, "sales_tax_pct", 0.08, 0.0, 0.15)
    now = db.now_iso()
    eid = db.new_id()
    event = {
        "id": eid,
        "account_name": account_name,
        "event_date": event_date,
        "setup_style": setup_style,
        "expected_attendance": expected,
        "guarantee_count": None,
        "actual_attendance": None,
        "overset_pct": overset,
        "service_charge_pct": service_charge,
        "gratuity_pct": gratuity,
        "sales_tax_pct": sales_tax,
        "status": "INQUIRY",
        "estimated_total_cents": 0,
        "actualized_total_cents": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    # All totals derived from an empty set of children evaluate to 0.
    event["estimated_total_cents"] = svc.charge_rollup(event)
    db.events[eid] = event
    return success(svc.serialize_event(event), status=201)


@app.route("/events/<event_id>", methods=["GET"])
def get_event(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    event = helpers.get_event_or_404(event_id)
    return success(svc.serialize_event(event), status=200)


@app.route("/events", methods=["GET"])
def list_events():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = helpers.parse_pagination()
    status_filter = request.args.get("status")
    rows = list(db.events.values())
    if status_filter is not None:
        rows = [e for e in rows if e["status"] == status_filter]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_event)
    return list_success(items, limit, offset, total)


def _event_bookings(event_id):
    return [b for b in db.bookings.values() if b["event_id"] == event_id]


@app.route("/events/<event_id>/hold", methods=["POST"])
def event_hold(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    # State: only INQUIRY -> TENTATIVE is legal.
    if event["status"] != "INQUIRY":
        raise errors.invalid_state("hold requires status INQUIRY")
    bookings = [b for b in _event_bookings(event_id) if b["hold_status"] != "RELEASED"]
    if len(bookings) < 1:
        raise errors.no_bookings()
    # Every non-released booking must be HOLD or DEFINITE (always true here).
    event["status"] = "TENTATIVE"
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


@app.route("/events/<event_id>/confirm-space", methods=["POST"])
def event_confirm_space(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    if event["status"] != "TENTATIVE":
        raise errors.invalid_state("confirm-space requires status TENTATIVE")
    active = [b for b in _event_bookings(event_id) if b["hold_status"] != "RELEASED"]
    if len(active) < 1:
        raise errors.no_bookings()
    if any(b["hold_status"] == "HOLD" for b in active):
        raise errors.booking_not_all_definite()
    event["status"] = "DEFINITE"
    svc.recompute_estimated_total(event)
    svc.recompute_balance(event)
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


@app.route("/events/<event_id>/reopen", methods=["POST"])
def event_reopen(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    # DEFINITE -> TENTATIVE, only while guarantee not yet locked.
    if event["status"] != "DEFINITE" or event["guarantee_count"] is not None:
        raise errors.invalid_state("reopen requires DEFINITE status with no locked guarantee")
    event["status"] = "TENTATIVE"
    # Revert every DEFINITE booking to HOLD (cascade).
    for b in _event_bookings(event_id):
        if b["hold_status"] == "DEFINITE":
            b["hold_status"] = "HOLD"
            svc.touch(b)
    svc.recompute_estimated_total(event)
    svc.recompute_balance(event)
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


@app.route("/events/<event_id>/lock-guarantee", methods=["POST"])
def event_lock_guarantee(event_id):
    role = authenticate()
    require_role(role, {"BanquetCaptain"})
    event = helpers.get_event_or_404(event_id)
    body = get_json_body()
    # State gate first (priority 5).
    if event["status"] != "DEFINITE":
        raise errors.invalid_state("lock-guarantee requires status DEFINITE")
    # guarantee_count required and >= 1 (ERR_GUARANTEE_REQUIRED, 422).
    gc = body.get("guarantee_count")
    if not isinstance(gc, int) or isinstance(gc, bool) or gc < 1:
        raise errors.guarantee_required()
    # Deposit milestone (sequence_no==1) must be settled (priority 12).
    deposit = svc.deposit_item(event)
    if deposit is None or not deposit["settled"]:
        raise errors.deposit_unsettled()
    # Apply.
    event["guarantee_count"] = gc
    event["status"] = "CONFIRMED"
    # billable_count now reads the oversetted guarantee; cascade per-person lines.
    for m in db.menu_lines.values():
        if m["event_id"] == event_id and m["pricing_mode"] == "PER_PERSON":
            svc.recompute_menu_line(m, event)
    svc.recompute_estimated_total(event)
    svc.recompute_balance(event)
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


@app.route("/events/<event_id>/actualize", methods=["POST"])
def event_actualize(event_id):
    role = authenticate()
    require_role(role, {"BanquetCaptain"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    if event["status"] != "CONFIRMED":
        raise errors.invalid_state("actualize requires status CONFIRMED")
    actual = v.req_int(body, "actual_attendance", minimum=0)
    event["actual_attendance"] = actual
    event["status"] = "COMPLETED"
    # billable_count now max(guarantee, actual); cascade per-person lines.
    for m in db.menu_lines.values():
        if m["event_id"] == event_id and m["pricing_mode"] == "PER_PERSON":
            svc.recompute_menu_line(m, event)
    # actualized_total via the actual variant (status is COMPLETED now).
    event["actualized_total_cents"] = svc.charge_rollup(event)
    svc.recompute_balance(event)
    # Room-block cleanup: still-RESERVED links with no recorded pickup auto-released.
    for l in db.room_block_links.values():
        if l["event_id"] == event_id and l["link_status"] == "RESERVED":
            l["link_status"] = "RELEASED"
            svc.touch(l)
            _touch_block(l["hotel_room_block_id"])
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


@app.route("/events/<event_id>/cancel", methods=["POST"])
def event_cancel(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    if event["status"] not in {"INQUIRY", "TENTATIVE", "DEFINITE", "CONFIRMED"}:
        raise errors.invalid_state("cancel requires a non-terminal status")
    event["status"] = "CANCELLED"
    # Release all non-released bookings.
    for b in _event_bookings(event_id):
        if b["hold_status"] != "RELEASED":
            b["hold_status"] = "RELEASED"
            b["rental_charge_cents"] = 0
            svc.touch(b)
    # Release all non-released room-block links (cascade returns rooms to blocks).
    for l in db.room_block_links.values():
        if l["event_id"] == event_id and l["link_status"] != "RELEASED":
            l["link_status"] = "RELEASED"
            svc.touch(l)
            _touch_block(l["hotel_room_block_id"])
    # estimated_total_cents and actualized_total_cents frozen at last computed value.
    svc.touch_no_version(event)
    return success(svc.serialize_event(event), status=200)


def _touch_block(block_id):
    block = db.hotel_room_blocks.get(block_id)
    if block is not None:
        svc.touch(block)


# ===========================================================================
# FunctionRoomBooking
# ===========================================================================
@app.route("/events/<event_id>/bookings", methods=["POST"])
def create_booking(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    # Body shape (priority 4) — resolve FK, types, required fields.
    function_room_id = v.req_str(body, "function_room_id")
    start_utc = v.req_str(body, "start_utc")
    end_utc = v.req_str(body, "end_utc")
    setup_diagram_url = v.opt_str(body, "setup_diagram_url", default=None)
    # expected_event_version is a required field; wrong type/missing -> 400.
    expected_version = v.req_int(body, "expected_event_version")
    # FK existence (priority 3) reported as ERR_NOT_FOUND.
    room = db.function_rooms.get(function_room_id)
    if room is None:
        raise errors.not_found("FunctionRoom not found: " + str(function_room_id))
    # Validate datetimes and start < end.
    try:
        start_dt = svc.parse_dt(start_utc)
        end_dt = svc.parse_dt(end_utc)
    except Exception:
        raise errors.invalid_request("start_utc/end_utc must be ISO 8601 instants")
    if not (end_dt > start_dt):
        raise errors.invalid_request("end_utc must be strictly after start_utc")
    # OCC (priority 6).
    if expected_version != event["version"]:
        raise errors.stale_version()
    now = db.now_iso()
    bid = db.new_id()
    booking = {
        "id": bid,
        "event_id": event_id,
        "function_room_id": function_room_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "setup_diagram_url": setup_diagram_url,
        "hold_status": "HOLD",
        "rental_charge_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    booking["rental_charge_cents"] = svc.room_rental(booking, room)
    db.bookings[bid] = booking
    # A new booking changes the event's room-hold composition: bump version.
    svc.touch(event)
    return success(svc.serialize_booking(booking), status=201)


@app.route("/events/<event_id>/bookings", methods=["GET"])
def list_event_bookings(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    rows = _event_bookings(event_id)
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_booking)
    return list_success(items, limit, offset, total)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = helpers.parse_pagination()
    function_room_id = request.args.get("function_room_id")
    event_id = request.args.get("event_id")
    rows = list(db.bookings.values())
    if function_room_id is not None:
        rows = [b for b in rows if b["function_room_id"] == function_room_id]
    if event_id is not None:
        rows = [b for b in rows if b["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_booking)
    return list_success(items, limit, offset, total)


@app.route("/events/<event_id>/bookings/<booking_id>", methods=["GET"])
def get_booking(event_id, booking_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    booking = helpers.get_booking_or_404(event_id, booking_id)
    return success(svc.serialize_booking(booking), status=200)


@app.route("/events/<event_id>/bookings/<booking_id>/make-definite", methods=["POST"])
def booking_make_definite(event_id, booking_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    booking = helpers.get_booking_or_404(event_id, booking_id)
    # State: booking must be HOLD, owning event TENTATIVE or DEFINITE (priority 5).
    if booking["hold_status"] != "HOLD" or event["status"] not in {"TENTATIVE", "DEFINITE"}:
        raise errors.invalid_state("make-definite requires HOLD booking on a TENTATIVE/DEFINITE event")
    room = db.function_rooms.get(booking["function_room_id"])
    # Buffered double-booking check (priority 7) — higher priority than capacity.
    if _buffered_overlap_conflict(booking, room):
        raise errors.room_double_booked()
    # Capacity gate (priority 8).
    effective = svc.effective_room_capacity(room, event)
    if effective < svc.billable_count(event):
        raise errors.capacity_exceeded()
    booking["hold_status"] = "DEFINITE"
    booking["rental_charge_cents"] = svc.room_rental(booking, room)
    svc.touch(booking)
    return success(svc.serialize_booking(booking), status=200)


def _buffered_overlap_conflict(candidate, room):
    """Candidate window expanded by buffer on both sides must not intersect the
    RAW window of any other DEFINITE booking on the same room. Strict-inequality
    overlap (touching at an endpoint after expansion does not collide)."""
    buffer_min = room["turnover_buffer_minutes"]
    c_start = svc.parse_dt(candidate["start_utc"])
    c_end = svc.parse_dt(candidate["end_utc"])
    from datetime import timedelta
    exp_start = c_start - timedelta(minutes=buffer_min)
    exp_end = c_end + timedelta(minutes=buffer_min)
    for other in db.bookings.values():
        if other["id"] == candidate["id"]:
            continue
        if other["function_room_id"] != room["id"]:
            continue
        if other["hold_status"] != "DEFINITE":
            continue
        o_start = svc.parse_dt(other["start_utc"])
        o_end = svc.parse_dt(other["end_utc"])
        # Strict overlap: exp_start < o_end AND o_start < exp_end.
        if exp_start < o_end and o_start < exp_end:
            return True
    return False


@app.route("/events/<event_id>/bookings/<booking_id>/soften", methods=["POST"])
def booking_soften(event_id, booking_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    booking = helpers.get_booking_or_404(event_id, booking_id)
    if booking["hold_status"] != "DEFINITE" or event["status"] not in {"TENTATIVE", "DEFINITE"}:
        raise errors.invalid_state("soften requires DEFINITE booking on a TENTATIVE/DEFINITE event")
    booking["hold_status"] = "HOLD"
    svc.touch(booking)
    return success(svc.serialize_booking(booking), status=200)


@app.route("/events/<event_id>/bookings/<booking_id>/release", methods=["POST"])
def booking_release(event_id, booking_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    helpers.get_event_or_404(event_id)
    booking = helpers.get_booking_or_404(event_id, booking_id)
    if booking["hold_status"] not in {"HOLD", "DEFINITE"}:
        raise errors.invalid_state("release requires HOLD or DEFINITE booking")
    booking["hold_status"] = "RELEASED"
    booking["rental_charge_cents"] = 0
    svc.touch(booking)
    return success(svc.serialize_booking(booking), status=200)


# ===========================================================================
# MenuLine
# ===========================================================================
def _assert_event_not_terminal(event):
    if event["status"] in {"COMPLETED", "CANCELLED"}:
        raise errors.event_terminal()


@app.route("/events/<event_id>/menu-lines", methods=["POST"])
def create_menu_line(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    name = v.req_str(body, "name")
    pricing_mode = v.req_enum(body, "pricing_mode", {"PER_PERSON", "CONSUMPTION"})
    unit_price = v.req_int(body, "unit_price_cents", minimum=0)
    # Terminal-event guard (line edits blocked on COMPLETED/CANCELLED).
    _assert_event_not_terminal(event)
    # Pricing-mode field mismatch (priority 9, ERR_PRICING_MODE_FIELD_MISMATCH).
    consumption_qty = None
    has_qty = "consumption_qty" in body and body["consumption_qty"] is not None
    if pricing_mode == "PER_PERSON":
        if has_qty:
            raise errors.pricing_mode_field_mismatch()
    else:  # CONSUMPTION
        if not has_qty:
            raise errors.pricing_mode_field_mismatch()
        consumption_qty = v.req_int(body, "consumption_qty", minimum=0)
    now = db.now_iso()
    mid = db.new_id()
    line = {
        "id": mid,
        "event_id": event_id,
        "name": name,
        "pricing_mode": pricing_mode,
        "unit_price_cents": unit_price,
        "consumption_qty": consumption_qty,
        "extended_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    line["extended_cents"] = svc.menu_line_extended(line, event)
    db.menu_lines[mid] = line
    _recompute_event_total(event)
    return success(svc.serialize_menu_line(line), status=201)


@app.route("/events/<event_id>/menu-lines", methods=["GET"])
def list_menu_lines(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    rows = [m for m in db.menu_lines.values() if m["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_menu_line)
    return list_success(items, limit, offset, total)


@app.route("/events/<event_id>/menu-lines/<menu_line_id>", methods=["DELETE"])
def delete_menu_line(event_id, menu_line_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    line = helpers.get_menu_line_or_404(event_id, menu_line_id)
    _assert_event_not_terminal(event)
    del db.menu_lines[menu_line_id]
    _recompute_event_total(event)
    return success({}, status=204)


# ===========================================================================
# ServiceLine
# ===========================================================================
@app.route("/events/<event_id>/service-lines", methods=["POST"])
def create_service_line(event_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    category = v.req_enum(body, "category", {"AV", "LABOR", "RENTAL_ITEM"})
    description = v.req_str(body, "description")
    quantity = v.req_int(body, "quantity", minimum=1)
    unit_price = v.req_int(body, "unit_price_cents", minimum=0)
    gratuity_eligible = v.opt_bool(body, "gratuity_eligible", default=False)
    _assert_event_not_terminal(event)
    now = db.now_iso()
    sid = db.new_id()
    line = {
        "id": sid,
        "event_id": event_id,
        "category": category,
        "description": description,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "gratuity_eligible": gratuity_eligible,
        "extended_cents": quantity * unit_price,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.service_lines[sid] = line
    _recompute_event_total(event)
    return success(svc.serialize_service_line(line), status=201)


@app.route("/events/<event_id>/service-lines", methods=["GET"])
def list_service_lines(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    rows = [s for s in db.service_lines.values() if s["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_service_line)
    return list_success(items, limit, offset, total)


@app.route("/events/<event_id>/service-lines/<service_line_id>", methods=["DELETE"])
def delete_service_line(event_id, service_line_id):
    role = authenticate()
    require_role(role, {"SalesManager"})
    event = helpers.get_event_or_404(event_id)
    line = helpers.get_service_line_or_404(event_id, service_line_id)
    _assert_event_not_terminal(event)
    del db.service_lines[service_line_id]
    _recompute_event_total(event)
    return success({}, status=204)


def _recompute_event_total(event):
    """Adding/removing a line recomputes estimated_total_cents (and balance).
    Frozen on terminal events (the terminal guard precedes mutation calls)."""
    if event["status"] in {"COMPLETED", "CANCELLED"}:
        return
    svc.recompute_estimated_total(event)
    svc.recompute_balance(event)
    svc.touch_no_version(event)


# ===========================================================================
# RoomBlockLink
# ===========================================================================
@app.route("/events/<event_id>/room-block-links", methods=["POST"])
def create_room_block_link(event_id):
    role = authenticate()
    require_role(role, {"SalesManager", "AccountingClerk"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    hotel_room_block_id = v.req_str(body, "hotel_room_block_id")
    rooms_reserved = v.req_int(body, "rooms_reserved", minimum=1)
    check_in = v.req_str(body, "check_in_date")
    check_out = v.req_str(body, "check_out_date")
    # FK existence (priority 3).
    block = db.hotel_room_blocks.get(hotel_room_block_id)
    if block is None:
        raise errors.not_found("HotelRoomBlock not found: " + str(hotel_room_block_id))
    # Validate dates and check_out strictly after check_in.
    try:
        ci = datetime.fromisoformat(check_in).date()
        co = datetime.fromisoformat(check_out).date()
    except Exception:
        raise errors.invalid_request("check_in_date/check_out_date must be ISO dates")
    if not (co > ci):
        raise errors.invalid_request("check_out_date must be strictly after check_in_date")
    # Per-night aggregate-capacity gate (priority 11).
    if _block_night_overbooked(block, ci, co, rooms_reserved):
        raise errors.block_insufficient_rooms()
    now = db.now_iso()
    lid = db.new_id()
    link = {
        "id": lid,
        "event_id": event_id,
        "hotel_room_block_id": hotel_room_block_id,
        "rooms_reserved": rooms_reserved,
        "check_in_date": check_in,
        "check_out_date": check_out,
        "rooms_picked_up": None,
        "link_status": "RESERVED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.room_block_links[lid] = link
    _touch_block(hotel_room_block_id)
    return success(svc.serialize_room_block_link(link), status=201)


def _nights(check_in_str, check_out_str):
    """Half-open night set [check_in, check_out): list of date objects."""
    from datetime import timedelta
    ci = datetime.fromisoformat(check_in_str).date()
    co = datetime.fromisoformat(check_out_str).date()
    result = []
    d = ci
    while d < co:
        result.append(d)
        d += timedelta(days=1)
    return result


def _block_night_overbooked(block, ci_date, co_date, candidate_rooms):
    """For each night in the candidate's half-open [ci, co) range, the sum of
    active-link contributions plus candidate_rooms must not exceed total_rooms."""
    from datetime import timedelta
    active = [
        l for l in db.room_block_links.values()
        if l["hotel_room_block_id"] == block["id"] and l["link_status"] in {"RESERVED", "PICKED_UP"}
    ]
    # Build per-night occupancy from active links.
    candidate_nights = []
    d = ci_date
    while d < co_date:
        candidate_nights.append(d)
        d += timedelta(days=1)
    for night in candidate_nights:
        occupied = 0
        for l in active:
            l_nights = set(_nights(l["check_in_date"], l["check_out_date"]))
            if night in l_nights:
                if l["link_status"] == "RESERVED":
                    occupied += l["rooms_reserved"]
                else:  # PICKED_UP
                    occupied += l["rooms_picked_up"] if l["rooms_picked_up"] is not None else 0
        if occupied + candidate_rooms > block["total_rooms"]:
            return True
    return False


@app.route("/events/<event_id>/room-block-links", methods=["GET"])
def list_event_links(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    rows = [l for l in db.room_block_links.values() if l["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_room_block_link)
    return list_success(items, limit, offset, total)


@app.route("/room-block-links", methods=["GET"])
def list_links():
    role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = helpers.parse_pagination()
    hotel_room_block_id = request.args.get("hotel_room_block_id")
    event_id = request.args.get("event_id")
    rows = list(db.room_block_links.values())
    if hotel_room_block_id is not None:
        rows = [l for l in rows if l["hotel_room_block_id"] == hotel_room_block_id]
    if event_id is not None:
        rows = [l for l in rows if l["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_room_block_link)
    return list_success(items, limit, offset, total)


@app.route("/events/<event_id>/room-block-links/<link_id>/record-pickup", methods=["POST"])
def link_record_pickup(event_id, link_id):
    role = authenticate()
    require_role(role, {"AccountingClerk"})
    event = helpers.get_event_or_404(event_id)
    link = helpers.get_link_or_404(event_id, link_id)
    body = v.require_body(get_json_body())
    # State: RESERVED -> PICKED_UP, owning event CONFIRMED or COMPLETED (priority 5).
    if link["link_status"] != "RESERVED" or event["status"] not in {"CONFIRMED", "COMPLETED"}:
        raise errors.invalid_state("record-pickup requires a RESERVED link on a CONFIRMED/COMPLETED event")
    rooms_picked_up = v.req_int(body, "rooms_picked_up")
    # rooms_picked_up within [0, rooms_reserved] (priority 10).
    if rooms_picked_up < 0 or rooms_picked_up > link["rooms_reserved"]:
        raise errors.pickup_exceeds_reserved()
    link["rooms_picked_up"] = rooms_picked_up
    link["link_status"] = "PICKED_UP"
    svc.touch(link)
    _touch_block(link["hotel_room_block_id"])
    return success(svc.serialize_room_block_link(link), status=200)


@app.route("/events/<event_id>/room-block-links/<link_id>/release", methods=["POST"])
def link_release(event_id, link_id):
    role = authenticate()
    require_role(role, {"AccountingClerk"})
    helpers.get_event_or_404(event_id)
    link = helpers.get_link_or_404(event_id, link_id)
    if link["link_status"] not in {"RESERVED", "PICKED_UP"}:
        raise errors.invalid_state("release requires a RESERVED or PICKED_UP link")
    link["link_status"] = "RELEASED"
    svc.touch(link)
    _touch_block(link["hotel_room_block_id"])
    return success(svc.serialize_room_block_link(link), status=200)


# ===========================================================================
# PaymentScheduleItem
# ===========================================================================
@app.route("/events/<event_id>/payment-schedule-items", methods=["POST"])
def create_payment_schedule_item(event_id):
    role = authenticate()
    require_role(role, {"AccountingClerk"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    label = v.req_str(body, "label")
    due_date = v.req_str(body, "due_date")
    amount_due = v.req_int(body, "amount_due_cents", minimum=1)
    # Assign sequence_no (1-based, monotonically increasing per event).
    existing = [i for i in db.payment_schedule_items.values() if i["event_id"] == event_id]
    seq = max((i["sequence_no"] for i in existing), default=0) + 1
    now = db.now_iso()
    iid = db.new_id()
    item = {
        "id": iid,
        "event_id": event_id,
        "label": label,
        "due_date": due_date,
        "amount_due_cents": amount_due,
        "sequence_no": seq,
        "allocated_cents": 0,
        "settled": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.payment_schedule_items[iid] = item
    # Re-run the waterfall (allocations may now fill this item).
    svc.run_waterfall(event)
    svc.recompute_balance(event)
    return success(svc.serialize_payment_schedule_item(item), status=201)


@app.route("/events/<event_id>/payment-schedule-items", methods=["GET"])
def list_payment_schedule_items(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    rows = [i for i in db.payment_schedule_items.values() if i["event_id"] == event_id]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_payment_schedule_item)
    return list_success(items, limit, offset, total)


# ===========================================================================
# Payment (event log)
# ===========================================================================
@app.route("/events/<event_id>/payments", methods=["POST"])
def create_payment(event_id):
    role = authenticate()
    require_role(role, {"AccountingClerk"})
    event = helpers.get_event_or_404(event_id)
    body = v.require_body(get_json_body())
    amount = v.req_int(body, "amount_cents", minimum=1)
    method = v.req_enum(body, "method", {"CARD", "ACH", "CHECK", "WIRE"})
    expected_version = v.req_int(body, "expected_event_version")
    # OCC (priority 6).
    if expected_version != event["version"]:
        raise errors.stale_version()
    now = db.now_iso()
    pid = db.new_id()
    payment = {
        "id": pid,
        "event_id": event_id,
        "amount_cents": amount,
        "method": method,
        "status": "APPLIED",
        "created_at": now,
        "_seq": db.next_seq(),
    }
    db.payments[pid] = payment
    # Recompute paid_to_date, re-run waterfall, recompute balance.
    svc.run_waterfall(event)
    svc.recompute_balance(event)
    # A successful payment record increments the event's version by one.
    svc.touch(event)
    return success(svc.serialize_payment(payment), status=201)


@app.route("/events/<event_id>/payments", methods=["GET"])
def list_payments(event_id):
    role = authenticate()
    require_role(role, ALL_ROLES)
    helpers.get_event_or_404(event_id)
    limit, offset = helpers.parse_pagination()
    status_filter = request.args.get("status")
    rows = [p for p in db.payments.values() if p["event_id"] == event_id]
    if status_filter is not None:
        rows = [p for p in rows if p["status"] == status_filter]
    items, total = helpers.paginate(rows, limit, offset, svc.serialize_payment)
    return list_success(items, limit, offset, total)


@app.route("/events/<event_id>/payments/<payment_id>/void", methods=["POST"])
def void_payment(event_id, payment_id):
    role = authenticate()
    require_role(role, {"AccountingClerk"})
    event = helpers.get_event_or_404(event_id)
    payment = helpers.get_payment_or_404(event_id, payment_id)
    # State: payment must be APPLIED (priority 5).
    if payment["status"] != "APPLIED":
        raise errors.invalid_state("void requires an APPLIED payment")
    # Owning event must not be COMPLETED (terminal) -> ERR_EVENT_TERMINAL.
    if event["status"] == "COMPLETED":
        raise errors.event_terminal()
    # Fiscal guard (priority 13): a void must not unsettle a settled deposit on a
    # CONFIRMED event.
    if event["status"] == "CONFIRMED":
        deposit = svc.deposit_item(event)
        if deposit is not None and deposit["settled"]:
            # Simulate the void: would the deposit still be settled?
            remaining_pool = svc.paid_to_date(event) - payment["amount_cents"]
            if remaining_pool < deposit["amount_due_cents"]:
                raise errors.deposit_locked()
    payment["status"] = "VOIDED"
    # Recompute paid_to_date, re-run waterfall, recompute balance.
    svc.run_waterfall(event)
    svc.recompute_balance(event)
    return success(svc.serialize_payment(payment), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # The runner reboots this process before every per-test run (8 rounds run
    # concurrently), so the boot path must be as lean as possible and must not
    # spend time on per-request access logging — under 8x CPU contention that
    # overhead is what tips a boot past the readiness window. Silence Werkzeug's
    # request logger so each handled request skips the stderr access-log write.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        debug=False,
        use_reloader=False,
    )
