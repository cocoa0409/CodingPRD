"""Karaoke Private Room Booking API — Flask entry point.

In-memory only (db.py). No seeding at startup. start.sh re-invocation wipes
all state because the process restarts with empty module-level dicts.

Validation ordering follows PRD §2.8:
  1 auth (ERR_UNAUTHENTICATED) -> 2 authz (ERR_FORBIDDEN)
  -> 3 existence (ERR_NOT_FOUND) -> 4 well-formedness (ERR_INVALID_REQUEST)
  -> 5 state (ERR_INVALID_STATE) -> 6 OCC -> 7 timing -> 8 capacity
  -> 9 room/type match -> 10 double-book -> 11 ext conflict
  -> 12 room-not-available -> 13 not-queue-head.
"""

import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, request

import calculations
import db
import errors
import helpers
import middleware
import response
import serialize
import services

app = Flask(__name__)


# =============================================================================
# Error handling
# =============================================================================

@app.errorhandler(errors.ApiError)
def handle_api_error(err):
    return response.error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(_e):
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(_e):
    # Method not allowed on a known path — treat as not found for routing.
    return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, errors.ApiError):
        return handle_api_error(err)
    return response.error_response("ERR_VALIDATION", str(err), 422)


# =============================================================================
# Existence helpers (ERR_NOT_FOUND, PRD §2.5 left-to-right)
# =============================================================================

def must_venue(venue_id):
    v = db.venues.get(venue_id)
    if v is None:
        raise errors.not_found("Venue not found.")
    return v


def must_room_type(rt_id):
    rt = db.room_types.get(rt_id)
    if rt is None:
        raise errors.not_found("Room type not found.")
    return rt


def must_room(room_id):
    r = db.rooms.get(room_id)
    if r is None:
        raise errors.not_found("Room not found.")
    return r


def must_group_package(gp_id):
    gp = db.group_packages.get(gp_id)
    if gp is None:
        raise errors.not_found("Group package not found.")
    return gp


def must_customer(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise errors.not_found("Customer not found.")
    return c


def must_reservation(reservation_id):
    r = db.reservations.get(reservation_id)
    if r is None:
        raise errors.not_found("Reservation not found.")
    return r


def must_song(song_id):
    s = db.songs.get(song_id)
    if s is None:
        raise errors.not_found("Song not found.")
    return s


def must_queue_entry(qe_id):
    qe = db.queue_entries.get(qe_id)
    if qe is None:
        raise errors.not_found("Queue entry not found.")
    return qe


def must_fb_order(fb_id):
    fb = db.fb_orders.get(fb_id)
    if fb is None:
        raise errors.not_found("F&B order not found.")
    return fb


def must_payment(pid):
    p = db.payments.get(pid)
    if p is None:
        raise errors.not_found("Payment not found.")
    return p


# =============================================================================
# Ownership (PRD §2.1): Customer may act only on own reservations / children
# =============================================================================

def assert_reservation_owner(reservation, user_id, role):
    if role == "Customer" and reservation["customer_id"] != user_id:
        raise errors.forbidden("Customer does not own this reservation.")


# =============================================================================
# Generic list responder
# =============================================================================

def list_response(items, serializer, presorted=False):
    limit, offset = helpers.parse_pagination()
    if not presorted:
        items = helpers.sort_by_created(items)
    page, total = helpers.paginate(items, limit, offset)
    data = [serializer(x) for x in page]
    return response.array_response(data, limit, offset, total)


# =============================================================================
# Venue endpoints (PRD §3.1, §2.9)
# =============================================================================

@app.route("/venues", methods=["POST"])
def create_venue():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager"})
    body = helpers.get_body()

    name = helpers.as_string(helpers.require_field(body, "name"), "name")
    timezone = helpers.as_string(helpers.require_field(body, "timezone"), "timezone")
    peak_start = helpers.as_int(
        helpers.require_field(body, "peak_start_minute"), "peak_start_minute", 0, 1439
    )
    peak_end = helpers.as_int(
        helpers.require_field(body, "peak_end_minute"), "peak_end_minute", 0, 1439
    )
    if peak_start >= peak_end:
        raise errors.invalid_request("peak_start_minute must be < peak_end_minute.")

    peak_multiplier = helpers.opt_field(body, "peak_multiplier", 1.5)
    peak_multiplier = helpers.as_number(peak_multiplier, "peak_multiplier", minimum=1.0)
    deposit_pct = helpers.opt_field(body, "deposit_pct", 0.2)
    deposit_pct = helpers.as_number(deposit_pct, "deposit_pct", exclusive_min=0, maximum=1)
    cancellation_cutoff_hours = helpers.opt_field(body, "cancellation_cutoff_hours", 24)
    cancellation_cutoff_hours = helpers.as_int(
        cancellation_cutoff_hours, "cancellation_cutoff_hours", minimum=0
    )
    grace_minutes = helpers.opt_field(body, "grace_minutes", 15)
    grace_minutes = helpers.as_int(grace_minutes, "grace_minutes", minimum=0)
    overage_grace_minutes = helpers.opt_field(body, "overage_grace_minutes", 10)
    overage_grace_minutes = helpers.as_int(
        overage_grace_minutes, "overage_grace_minutes", minimum=0
    )

    with db.lock:
        vid = db.new_id()
        ts = db.now_iso()
        venue = {
            "id": vid,
            "name": name,
            "timezone": timezone,
            "peak_start_minute": peak_start,
            "peak_end_minute": peak_end,
            "peak_multiplier": peak_multiplier,
            "deposit_pct": deposit_pct,
            "cancellation_cutoff_hours": cancellation_cutoff_hours,
            "grace_minutes": grace_minutes,
            "overage_grace_minutes": overage_grace_minutes,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.venues[vid] = venue
    return response.object_response(serialize.venue(venue), 201)


@app.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    middleware.get_identity()
    v = must_venue(venue_id)
    return response.object_response(serialize.venue(v), 200)


@app.route("/venues/<venue_id>/_clock/set", methods=["POST"])
def set_clock(venue_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager", "FrontDesk"})
    v = must_venue(venue_id)
    body = helpers.get_body()
    now_utc = helpers.require_field(body, "now_utc")
    dt = helpers.parse_dt(now_utc, "now_utc")
    with db.lock:
        # Store normalized ISO; mutation of the clock does not bump venue version.
        db.venue_clocks[venue_id] = _to_iso(dt)
    return response.object_response(serialize.venue(v), 200)


@app.route("/venues/<venue_id>/_ops/run", methods=["POST"])
def ops_run(venue_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager", "FrontDesk"})
    v = must_venue(venue_id)
    with db.lock:
        services.run_ops_sweep(venue_id)
    return response.object_response(serialize.venue(v), 200)


def _to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# =============================================================================
# RoomType endpoints (PRD §3.1)
# =============================================================================

ROOM_TYPE_NAMES = {"SMALL", "MEDIUM", "LARGE", "VIP"}


@app.route("/room-types", methods=["POST"])
def create_room_type():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager"})
    body = helpers.get_body()
    venue_id = helpers.as_string(helpers.require_field(body, "venue_id"), "venue_id")
    must_venue(venue_id)

    name = helpers.as_enum(helpers.require_field(body, "name"), "name", ROOM_TYPE_NAMES)
    capacity = helpers.as_int(helpers.require_field(body, "capacity"), "capacity", minimum=1)
    base_rate = helpers.as_int(
        helpers.require_field(body, "base_hourly_rate_cents"),
        "base_hourly_rate_cents", minimum=0,
    )
    fb_minimum = helpers.opt_field(body, "fb_minimum_cents", 0)
    fb_minimum = helpers.as_int(fb_minimum, "fb_minimum_cents", minimum=0)
    active = helpers.opt_field(body, "active", True)
    active = helpers.as_bool(active, "active")

    with db.lock:
        rid = db.new_id()
        ts = db.now_iso()
        rt = {
            "id": rid,
            "venue_id": venue_id,
            "name": name,
            "capacity": capacity,
            "base_hourly_rate_cents": base_rate,
            "fb_minimum_cents": fb_minimum,
            "active": active,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.room_types[rid] = rt
    return response.object_response(serialize.room_type(rt), 201)


@app.route("/room-types", methods=["GET"])
def list_room_types():
    middleware.get_identity()
    venue_id = request.args.get("venue_id")
    items = [
        rt for rt in db.room_types.values()
        if venue_id is None or rt["venue_id"] == venue_id
    ]
    return list_response(items, serialize.room_type)


@app.route("/room-types/<room_type_id>", methods=["GET"])
def get_room_type(room_type_id):
    middleware.get_identity()
    rt = must_room_type(room_type_id)
    return response.object_response(serialize.room_type(rt), 200)


# =============================================================================
# Room endpoints (PRD §3.1)
# =============================================================================

@app.route("/rooms", methods=["POST"])
def create_room():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager"})
    body = helpers.get_body()
    venue_id = helpers.as_string(helpers.require_field(body, "venue_id"), "venue_id")
    must_venue(venue_id)
    room_type_id = helpers.as_string(
        helpers.require_field(body, "room_type_id"), "room_type_id"
    )
    rt = must_room_type(room_type_id)
    if rt["venue_id"] != venue_id:
        raise errors.not_found("Room type not found in venue scope.")
    label = helpers.as_string(helpers.require_field(body, "label"), "label")

    with db.lock:
        rid = db.new_id()
        ts = db.now_iso()
        room = {
            "id": rid,
            "venue_id": venue_id,
            "room_type_id": room_type_id,
            "label": label,
            "status": "AVAILABLE",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.rooms[rid] = room
    return response.object_response(serialize.room(room), 201)


@app.route("/rooms", methods=["GET"])
def list_rooms():
    middleware.get_identity()
    venue_id = request.args.get("venue_id")
    room_type_id = request.args.get("room_type_id")
    items = [
        r for r in db.rooms.values()
        if (venue_id is None or r["venue_id"] == venue_id)
        and (room_type_id is None or r["room_type_id"] == room_type_id)
    ]
    return list_response(items, serialize.room)


@app.route("/rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    middleware.get_identity()
    r = must_room(room_id)
    return response.object_response(serialize.room(r), 200)


@app.route("/rooms/<room_id>/maintenance", methods=["POST"])
def room_maintenance(room_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager"})
    room = must_room(room_id)
    body = helpers.get_body()
    target = helpers.as_enum(
        helpers.require_field(body, "target"), "target",
        {"AVAILABLE", "OUT_OF_SERVICE"},
    )

    with db.lock:
        if target == "OUT_OF_SERVICE":
            # Only an AVAILABLE room may be taken OUT_OF_SERVICE (PRD §3.1).
            if room["status"] != "AVAILABLE":
                raise errors.room_not_available()
            room["status"] = "OUT_OF_SERVICE"
            services.touch(room)
        else:  # target AVAILABLE
            if room["status"] != "OUT_OF_SERVICE":
                # Returning to service is only legal from OUT_OF_SERVICE.
                raise errors.invalid_state("Room is not OUT_OF_SERVICE.")
            room["status"] = "AVAILABLE"
            services.touch(room)
    return response.object_response(serialize.room(room), 200)


# =============================================================================
# GroupPackage endpoints (PRD §3.2)
# =============================================================================

@app.route("/group-packages", methods=["POST"])
def create_group_package():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager"})
    body = helpers.get_body()
    venue_id = helpers.as_string(helpers.require_field(body, "venue_id"), "venue_id")
    must_venue(venue_id)
    name = helpers.as_string(helpers.require_field(body, "name"), "name")
    flat_price = helpers.as_int(
        helpers.require_field(body, "flat_price_cents"), "flat_price_cents", minimum=0
    )
    included_hours = helpers.as_number(
        helpers.require_field(body, "included_hours"), "included_hours", exclusive_min=0
    )
    included_rt_id = helpers.as_string(
        helpers.require_field(body, "included_room_type_id"), "included_room_type_id"
    )
    rt = must_room_type(included_rt_id)
    if rt["venue_id"] != venue_id:
        raise errors.not_found("Included room type not found in venue scope.")
    included_fb_credit = helpers.opt_field(body, "included_fb_credit_cents", 0)
    included_fb_credit = helpers.as_int(
        included_fb_credit, "included_fb_credit_cents", minimum=0
    )
    active = helpers.opt_field(body, "active", True)
    active = helpers.as_bool(active, "active")

    with db.lock:
        gid = db.new_id()
        ts = db.now_iso()
        gp = {
            "id": gid,
            "venue_id": venue_id,
            "name": name,
            "flat_price_cents": flat_price,
            "included_hours": included_hours,
            "included_room_type_id": included_rt_id,
            "included_fb_credit_cents": included_fb_credit,
            "active": active,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.group_packages[gid] = gp
    return response.object_response(serialize.group_package(gp), 201)


@app.route("/group-packages", methods=["GET"])
def list_group_packages():
    middleware.get_identity()
    venue_id = request.args.get("venue_id")
    included_rt_id = request.args.get("included_room_type_id")
    items = [
        gp for gp in db.group_packages.values()
        if (venue_id is None or gp["venue_id"] == venue_id)
        and (included_rt_id is None or gp["included_room_type_id"] == included_rt_id)
    ]
    return list_response(items, serialize.group_package)


@app.route("/group-packages/<group_package_id>", methods=["GET"])
def get_group_package(group_package_id):
    middleware.get_identity()
    gp = must_group_package(group_package_id)
    return response.object_response(serialize.group_package(gp), 200)


# =============================================================================
# Customer endpoints (PRD §3.2)
# =============================================================================

@app.route("/customers", methods=["POST"])
def create_customer():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    body = helpers.get_body()
    full_name = helpers.as_string(helpers.require_field(body, "full_name"), "full_name")
    email = helpers.as_string(helpers.require_field(body, "email"), "email")
    phone = helpers.as_string(helpers.require_field(body, "phone"), "phone")

    with db.lock:
        # email must be unique (PRD §3.2).
        for c in db.customers.values():
            if c["email"] == email:
                raise errors.invalid_request("email must be unique.")
        cid = db.new_id()
        ts = db.now_iso()
        customer = {
            "id": cid,
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "no_show_strikes": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.customers[cid] = customer
    return response.object_response(serialize.customer(customer), 201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    middleware.get_identity()
    c = must_customer(customer_id)
    return response.object_response(serialize.customer(c), 200)


# =============================================================================
# Song endpoints (PRD §3.2)
# =============================================================================

SONG_LANGUAGES = {"EN", "JP", "KR", "ZH", "ES", "OTHER"}


@app.route("/songs", methods=["POST"])
def create_song():
    _, role = middleware.get_identity()
    middleware.require_role(role, {"VenueManager", "FrontDesk"})
    body = helpers.get_body()
    venue_id = helpers.as_string(helpers.require_field(body, "venue_id"), "venue_id")
    must_venue(venue_id)
    title = helpers.as_string(helpers.require_field(body, "title"), "title")
    artist = helpers.as_string(helpers.require_field(body, "artist"), "artist")
    duration = helpers.as_int(
        helpers.require_field(body, "duration_seconds"), "duration_seconds", minimum=1
    )
    language = helpers.as_enum(
        helpers.require_field(body, "language"), "language", SONG_LANGUAGES
    )

    with db.lock:
        sid = db.new_id()
        ts = db.now_iso()
        song = {
            "id": sid,
            "venue_id": venue_id,
            "title": title,
            "artist": artist,
            "duration_seconds": duration,
            "language": language,
            "created_at": ts,
        }
        db.songs[sid] = song
    return response.object_response(serialize.song(song), 201)


@app.route("/songs", methods=["GET"])
def list_songs():
    middleware.get_identity()
    venue_id = request.args.get("venue_id")
    language = request.args.get("language")
    items = [
        s for s in db.songs.values()
        if (venue_id is None or s["venue_id"] == venue_id)
        and (language is None or s["language"] == language)
    ]
    return list_response(items, serialize.song)


@app.route("/songs/<song_id>", methods=["GET"])
def get_song(song_id):
    middleware.get_identity()
    s = must_song(song_id)
    return response.object_response(serialize.song(s), 200)


# =============================================================================
# Reservation endpoints (PRD §3.3 - §3.7)
# =============================================================================

@app.route("/reservations", methods=["POST"])
def create_reservation():
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    body = helpers.get_body()

    # --- existence (priority 3): venue, room, customer, optional package ------
    venue_id = helpers.as_string(helpers.require_field(body, "venue_id"), "venue_id")
    venue = must_venue(venue_id)
    room_id = helpers.as_string(helpers.require_field(body, "room_id"), "room_id")
    room = must_room(room_id)
    if room["venue_id"] != venue_id:
        raise errors.not_found("Room not found in venue scope.")
    customer_id = helpers.as_string(
        helpers.require_field(body, "customer_id"), "customer_id"
    )
    customer = must_customer(customer_id)
    group_package_id = helpers.opt_field(body, "group_package_id", None)
    gp = None
    if group_package_id is not None:
        group_package_id = helpers.as_string(group_package_id, "group_package_id")
        gp = must_group_package(group_package_id)
        if gp["venue_id"] != venue_id:
            raise errors.not_found("Group package not found in venue scope.")

    # Customer ownership: a Customer may only book for themselves (PRD §2.1).
    if role == "Customer" and customer_id != user_id:
        raise errors.forbidden("Customer may only book their own reservation.")

    # --- well-formedness (priority 4) ----------------------------------------
    party_size = helpers.as_int(
        helpers.require_field(body, "party_size"), "party_size", minimum=1
    )
    slot_start = helpers.parse_dt(
        helpers.require_field(body, "slot_start_utc"), "slot_start_utc"
    )
    slot_end = helpers.parse_dt(
        helpers.require_field(body, "slot_end_utc"), "slot_end_utc"
    )
    if slot_end <= slot_start:
        raise errors.invalid_request("slot_end_utc must be strictly after slot_start_utc.")
    expected_room_version = helpers.as_int(
        helpers.require_field(body, "expected_room_version"),
        "expected_room_version", minimum=0,
    )

    room_type = db.room_types.get(room["room_type_id"])

    with db.lock:
        # --- OCC (priority 6): expected_room_version vs current --------------
        if expected_room_version != room["version"]:
            raise errors.stale_room_version()

        # --- capacity (priority 8) -------------------------------------------
        if party_size > room_type["capacity"]:
            raise errors.capacity_exceeded()

        # --- room/type match (priority 9) ------------------------------------
        if not room_type["active"]:
            raise errors.room_type_mismatch("Room type is inactive.")
        if gp is not None and gp["included_room_type_id"] != room["room_type_id"]:
            raise errors.room_type_mismatch(
                "Package included_room_type_id does not match room's room_type_id."
            )

        # --- double-booking (priority 10) ------------------------------------
        if services.has_room_conflict(room_id, slot_start, slot_end):
            raise errors.room_double_booked()

        rid = db.new_id()
        ts = db.now_iso()
        reservation = {
            "id": rid,
            "venue_id": venue_id,
            "room_id": room_id,
            "room_type_id": room["room_type_id"],
            "customer_id": customer_id,
            "group_package_id": group_package_id,
            "party_size": party_size,
            "slot_start_utc": _to_iso(slot_start),
            "slot_end_utc": _to_iso(slot_end),
            "status": "HELD",
            "checked_in_at": None,
            "actual_end_utc": None,
            "quoted_room_subtotal_cents": None,
            "deposit_cents": None,
            "settled_room_subtotal_cents": None,
            "fb_consumed_cents": 0,
            "fb_shortfall_cents": 0,
            "final_total_cents": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.reservations[rid] = reservation
        # Preview computations (PRD §3.3): quote + deposit, fb preview.
        services.recompute_quote_preview(reservation)
        services.recompute_fb_preview(reservation)
        # Create-with-supersede (PRD §2.7): a booking created against the room
        # advances the room's version so a later create against a stale view of
        # the room is refused (ERR_STALE_ROOM_VERSION). The room is mutated, so
        # its updated_at + version bump by 1 (PRD §2.4/§2.5).
        services.touch(room)
    return response.object_response(serialize.reservation(reservation), 201)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    middleware.get_identity()
    a = request.args
    venue_id = a.get("venue_id")
    room_id = a.get("room_id")
    customer_id = a.get("customer_id")
    group_package_id = a.get("group_package_id")
    room_type_id = a.get("room_type_id")
    status = a.get("status")
    items = []
    for r in db.reservations.values():
        if venue_id is not None and r["venue_id"] != venue_id:
            continue
        if room_id is not None and r["room_id"] != room_id:
            continue
        if customer_id is not None and r["customer_id"] != customer_id:
            continue
        if group_package_id is not None and r["group_package_id"] != group_package_id:
            continue
        if room_type_id is not None and r["room_type_id"] != room_type_id:
            continue
        if status is not None and r["status"] != status:
            continue
        items.append(r)
    return list_response(items, serialize.reservation)


@app.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    middleware.get_identity()
    r = must_reservation(reservation_id)
    return response.object_response(serialize.reservation(r), 200)


@app.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    r = must_reservation(reservation_id)
    assert_reservation_owner(r, user_id, role)

    with db.lock:
        # state (priority 5): confirm requires HELD.
        if r["status"] != "HELD":
            raise errors.invalid_state("Reservation is not HELD.")
        # timing (priority 7): current_utc < slot_start_utc.
        now = helpers.current_utc(r["venue_id"])
        slot_start = helpers.parse_stored_dt(r["slot_start_utc"])
        if not (now < slot_start):
            raise errors.timing_window("Cannot confirm a slot whose start has passed.")
        # capacity (priority 8).
        room_type = db.room_types.get(r["room_type_id"])
        if r["party_size"] > room_type["capacity"]:
            raise errors.capacity_exceeded()

        r["status"] = "CONFIRMED"
        services.recompute_quote_preview(r)
        services.append_payment(r["id"], "DEPOSIT", r["deposit_cents"])
        services.touch(r)
    return response.object_response(serialize.reservation(r), 200)


@app.route("/reservations/<reservation_id>/check-in", methods=["POST"])
def check_in_reservation(reservation_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"FrontDesk"})
    r = must_reservation(reservation_id)

    with db.lock:
        # state (priority 5): check-in requires CONFIRMED.
        if r["status"] != "CONFIRMED":
            raise errors.invalid_state("Reservation is not CONFIRMED.")
        # timing (priority 7): current_utc <= slot_start + grace.
        venue = db.venues[r["venue_id"]]
        now = helpers.current_utc(r["venue_id"])
        slot_start = helpers.parse_stored_dt(r["slot_start_utc"])
        deadline = slot_start + timedelta(minutes=venue["grace_minutes"])
        if not (now <= deadline):
            raise errors.timing_window("Check-in is past the grace window.")
        # Room must be AVAILABLE (not OCCUPIED / OUT_OF_SERVICE).
        room = db.rooms[r["room_id"]]
        if room["status"] != "AVAILABLE":
            raise errors.invalid_state("Assigned room is not AVAILABLE.")

        r["status"] = "CHECKED_IN"
        r["checked_in_at"] = _to_iso(now)
        services.occupy_room(room)
        services.touch(r)
    return response.object_response(serialize.reservation(r), 200)


@app.route("/reservations/<reservation_id>/close", methods=["POST"])
def close_reservation(reservation_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"FrontDesk"})
    r = must_reservation(reservation_id)
    body = helpers.get_body()
    actual_end = helpers.parse_dt(
        helpers.require_field(body, "actual_end_utc"), "actual_end_utc"
    )

    with db.lock:
        # state (priority 5): close requires CHECKED_IN.
        if r["status"] != "CHECKED_IN":
            raise errors.invalid_state("Reservation is not CHECKED_IN.")
        # timing (priority 7): actual_end_utc >= checked_in_at.
        checked_in = helpers.parse_stored_dt(r["checked_in_at"])
        if actual_end < checked_in:
            raise errors.timing_window("actual_end_utc precedes checked_in_at.")

        r["status"] = "CLOSED"
        r["actual_end_utc"] = _to_iso(actual_end)

        venue = db.venues[r["venue_id"]]
        room_type = db.room_types.get(r["room_type_id"])
        gp = services.get_group_package(r)

        settled = calculations.settled_room_subtotal(r, venue, room_type, gp)
        r["settled_room_subtotal_cents"] = settled
        r["fb_consumed_cents"] = calculations.fb_consumed_cents(r["id"])
        r["fb_shortfall_cents"] = calculations.fb_shortfall_cents(r, room_type, gp)

        final_total = (
            settled + r["fb_consumed_cents"] + r["fb_shortfall_cents"] - r["deposit_cents"]
        )
        if final_total < 0:
            final_total = 0
        r["final_total_cents"] = final_total

        services.append_payment(r["id"], "SETTLEMENT", final_total)
        services.cascade_pending_queue(r["id"], "SKIPPED")
        room = db.rooms[r["room_id"]]
        services.free_room(room)
        services.touch(r)
    return response.object_response(serialize.reservation(r), 200)


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    r = must_reservation(reservation_id)
    assert_reservation_owner(r, user_id, role)

    with db.lock:
        # state (priority 5): cancel requires HELD or CONFIRMED.
        if r["status"] not in ("HELD", "CONFIRMED"):
            raise errors.invalid_state("Reservation cannot be cancelled from its state.")

        if r["status"] == "CONFIRMED":
            venue = db.venues[r["venue_id"]]
            now = helpers.current_utc(r["venue_id"])
            slot_start = helpers.parse_stored_dt(r["slot_start_utc"])
            cutoff = slot_start - timedelta(hours=venue["cancellation_cutoff_hours"])
            if now <= cutoff:
                # Outside cutoff -> refund deposit.
                services.append_payment(r["id"], "REFUND", r["deposit_cents"])
            else:
                # Inside cutoff -> forfeit deposit.
                services.append_payment(r["id"], "FORFEIT", r["deposit_cents"])
        # HELD: no deposit was collected -> no payment.

        r["status"] = "CANCELLED"
        services.cascade_pending_queue(r["id"], "CANCELLED")
        services.touch(r)
    return response.object_response(serialize.reservation(r), 200)


# =============================================================================
# Extension endpoints (PRD §3.5)
# =============================================================================

@app.route("/reservations/<reservation_id>/extensions", methods=["POST"])
def create_extension(reservation_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    r = must_reservation(reservation_id)
    assert_reservation_owner(r, user_id, role)
    body = helpers.get_body()

    new_end = helpers.parse_dt(
        helpers.require_field(body, "new_slot_end_utc"), "new_slot_end_utc"
    )
    expected_reservation_version = helpers.as_int(
        helpers.require_field(body, "expected_reservation_version"),
        "expected_reservation_version", minimum=0,
    )

    with db.lock:
        old_end = helpers.parse_stored_dt(r["slot_end_utc"])
        # well-formedness (priority 4): new end strictly after current end.
        if new_end <= old_end:
            raise errors.invalid_request(
                "new_slot_end_utc must be strictly after the current slot_end_utc."
            )
        # OCC (priority 6): expected_reservation_version vs current.
        if expected_reservation_version != r["version"]:
            raise errors.stale_reservation_version()
        # extension overlap (priority 11): [old_end, new_end) must be free.
        if services.has_room_conflict(
            r["room_id"], old_end, new_end, exclude_reservation_id=r["id"]
        ):
            raise errors.extension_conflict()

        added_minutes = int((new_end - old_end).total_seconds() // 60)
        eid = db.new_id()
        ts = db.now_iso()
        extension = {
            "id": eid,
            "reservation_id": r["id"],
            "new_slot_end_utc": _to_iso(new_end),
            "added_minutes": added_minutes,
            "status": "APPLIED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.extensions[eid] = extension
        # Advance the reservation interval and recompute previews.
        r["slot_end_utc"] = _to_iso(new_end)
        services.recompute_quote_preview(r)
        services.touch(r)
    return response.object_response(serialize.extension(extension), 201)


@app.route("/extensions", methods=["GET"])
def list_extensions():
    middleware.get_identity()
    reservation_id = request.args.get("reservation_id")
    items = [
        e for e in db.extensions.values()
        if reservation_id is None or e["reservation_id"] == reservation_id
    ]
    return list_response(items, serialize.extension)


@app.route("/extensions/<extension_id>", methods=["GET"])
def get_extension(extension_id):
    middleware.get_identity()
    e = db.extensions.get(extension_id)
    if e is None:
        raise errors.not_found("Extension not found.")
    return response.object_response(serialize.extension(e), 200)


# =============================================================================
# QueueEntry endpoints (PRD §3.6)
# =============================================================================

@app.route("/reservations/<reservation_id>/queue", methods=["POST"])
def queue_song(reservation_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    r = must_reservation(reservation_id)
    assert_reservation_owner(r, user_id, role)
    body = helpers.get_body()
    song_id = helpers.as_string(helpers.require_field(body, "song_id"), "song_id")
    must_song(song_id)
    priority = helpers.opt_field(body, "priority", 100)
    priority = helpers.as_int(priority, "priority")

    with db.lock:
        qid = db.new_id()
        ts = db.now_iso()
        qe = {
            "id": qid,
            "reservation_id": reservation_id,
            "song_id": song_id,
            "priority": priority,
            "play_order": None,
            "status": "PENDING",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.queue_entries[qid] = qe
        calculations.recompute_play_order(reservation_id)
    return response.object_response(serialize.queue_entry(qe), 201)


@app.route("/queue-entries", methods=["GET"])
def list_queue_entries():
    middleware.get_identity()
    a = request.args
    reservation_id = a.get("reservation_id")
    song_id = a.get("song_id")
    status = a.get("status")
    items = []
    for qe in db.queue_entries.values():
        if reservation_id is not None and qe["reservation_id"] != reservation_id:
            continue
        if song_id is not None and qe["song_id"] != song_id:
            continue
        if status is not None and qe["status"] != status:
            continue
        items.append(qe)
    # Queue listing is ordered by play_order; tie-break (priority ASC, created_at ASC).
    # PENDING entries first by play_order, then non-pending by created_at.
    def sort_key(qe):
        po = qe["play_order"]
        if po is None:
            return (1, 0, qe["created_at"], qe["id"])
        return (0, po, qe["created_at"], qe["id"])
    items = sorted(items, key=sort_key)
    return list_response(items, serialize.queue_entry, presorted=True)


@app.route("/queue-entries/<queue_entry_id>", methods=["GET"])
def get_queue_entry(queue_entry_id):
    middleware.get_identity()
    qe = must_queue_entry(queue_entry_id)
    return response.object_response(serialize.queue_entry(qe), 200)


@app.route("/queue-entries/<queue_entry_id>/play", methods=["POST"])
def play_queue_entry(queue_entry_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"FrontDesk"})
    qe = must_queue_entry(queue_entry_id)

    with db.lock:
        # state (priority 5): entry PENDING and parent CHECKED_IN.
        if qe["status"] != "PENDING":
            raise errors.invalid_state("Queue entry is not PENDING.")
        parent = db.reservations.get(qe["reservation_id"])
        if parent is None or parent["status"] != "CHECKED_IN":
            raise errors.invalid_state("Parent reservation is not CHECKED_IN.")
        # head-of-queue (priority 13): play_order == 1.
        calculations.recompute_play_order(qe["reservation_id"])
        if qe["play_order"] != 1:
            raise errors.not_queue_head()

        qe["status"] = "PLAYED"
        services.touch(qe)
        calculations.recompute_play_order(qe["reservation_id"])
    return response.object_response(serialize.queue_entry(qe), 200)


@app.route("/queue-entries/<queue_entry_id>/skip", methods=["POST"])
def skip_queue_entry(queue_entry_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"FrontDesk"})
    qe = must_queue_entry(queue_entry_id)

    with db.lock:
        if qe["status"] != "PENDING":
            raise errors.invalid_state("Queue entry is not PENDING.")
        qe["status"] = "SKIPPED"
        services.touch(qe)
        calculations.recompute_play_order(qe["reservation_id"])
    return response.object_response(serialize.queue_entry(qe), 200)


@app.route("/queue-entries/<queue_entry_id>", methods=["DELETE"])
def cancel_queue_entry(queue_entry_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    qe = must_queue_entry(queue_entry_id)
    parent = db.reservations.get(qe["reservation_id"])
    if parent is not None:
        assert_reservation_owner(parent, user_id, role)

    with db.lock:
        if qe["status"] != "PENDING":
            raise errors.invalid_state("Queue entry is not PENDING.")
        qe["status"] = "CANCELLED"
        services.touch(qe)
        calculations.recompute_play_order(qe["reservation_id"])
    return response.object_response(serialize.queue_entry(qe), 200)


# =============================================================================
# FbOrder endpoints (PRD §3.8)
# =============================================================================

@app.route("/reservations/<reservation_id>/fb-orders", methods=["POST"])
def create_fb_order(reservation_id):
    user_id, role = middleware.get_identity()
    middleware.require_role(role, {"Customer", "FrontDesk"})
    r = must_reservation(reservation_id)
    assert_reservation_owner(r, user_id, role)
    body = helpers.get_body()
    description = helpers.as_string(
        helpers.require_field(body, "description"), "description"
    )
    unit_price = helpers.as_int(
        helpers.require_field(body, "unit_price_cents"), "unit_price_cents", minimum=0
    )
    quantity = helpers.as_int(
        helpers.require_field(body, "quantity"), "quantity", minimum=1
    )

    with db.lock:
        fid = db.new_id()
        ts = db.now_iso()
        fb = {
            "id": fid,
            "reservation_id": reservation_id,
            "description": description,
            "unit_price_cents": unit_price,
            "quantity": quantity,
            "line_total_cents": unit_price * quantity,
            "status": "PLACED",
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        db.fb_orders[fid] = fb
        services.recompute_fb_preview(r)
    return response.object_response(serialize.fb_order(fb), 201)


@app.route("/fb-orders", methods=["GET"])
def list_fb_orders():
    middleware.get_identity()
    a = request.args
    reservation_id = a.get("reservation_id")
    status = a.get("status")
    items = []
    for fb in db.fb_orders.values():
        if reservation_id is not None and fb["reservation_id"] != reservation_id:
            continue
        if status is not None and fb["status"] != status:
            continue
        items.append(fb)
    return list_response(items, serialize.fb_order)


@app.route("/fb-orders/<fb_order_id>", methods=["GET"])
def get_fb_order(fb_order_id):
    middleware.get_identity()
    fb = must_fb_order(fb_order_id)
    return response.object_response(serialize.fb_order(fb), 200)


@app.route("/fb-orders/<fb_order_id>/void", methods=["POST"])
def void_fb_order(fb_order_id):
    _, role = middleware.get_identity()
    middleware.require_role(role, {"FrontDesk"})
    fb = must_fb_order(fb_order_id)

    with db.lock:
        if fb["status"] != "PLACED":
            raise errors.invalid_state("F&B order is not PLACED.")
        fb["status"] = "VOID"
        services.touch(fb)
        r = db.reservations.get(fb["reservation_id"])
        if r is not None:
            services.recompute_fb_preview(r)
    return response.object_response(serialize.fb_order(fb), 200)


# =============================================================================
# Payment endpoints (PRD §3.8)
# =============================================================================

@app.route("/payments", methods=["GET"])
def list_payments():
    middleware.get_identity()
    reservation_id = request.args.get("reservation_id")
    items = [
        p for p in db.payments.values()
        if reservation_id is None or p["reservation_id"] == reservation_id
    ]
    return list_response(items, serialize.payment)


@app.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    middleware.get_identity()
    p = must_payment(payment_id)
    return response.object_response(serialize.payment(p), 200)


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
