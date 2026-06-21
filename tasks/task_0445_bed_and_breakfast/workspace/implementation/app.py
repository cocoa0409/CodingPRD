"""Bed & Breakfast / Boutique Inn REST API.

Entry point: registers all routes, the global error handler, and runs the Flask
app bound to 0.0.0.0:$PORT (default 10000). In-memory storage, logical clock,
no seeding.
"""
import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request

import calculations as calc
import serialize as ser
from clock import clock
from db import db, new_id, now_iso
from errors import ApiError, err
from helpers import (
    as_bool, as_enum, as_int, as_str, get_booking_scoped_or_404, get_inn_or_404,
    get_json_body, get_scoped_or_404, paginate_params, parse_date_field, sort_and_page,
)
from middleware import get_caller, require_role
from pricing import recompute_booking_money, recompute_payment_fields
import response

app = Flask(__name__)
app.url_map.strict_slashes = False

DIETARY_FLAGS = {"VEGETARIAN", "VEGAN", "GLUTEN_FREE", "NUT_FREE", "DAIRY_FREE"}


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return response.error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return response.error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return response.error(e.error_id, e.http_status, e.message)
    return response.error("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % e)


# --------------------------------------------------------------------------- #
# System fields helpers
# --------------------------------------------------------------------------- #
def stamp_create(row, common=True):
    ts = now_iso()
    row["id"] = row.get("id") or new_id()
    row["created_at"] = ts
    row["_seq"] = db.next_seq()
    if common:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version (PRD §2.5, §2.8)."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


# --------------------------------------------------------------------------- #
# Clock (test-driving)
# --------------------------------------------------------------------------- #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    get_caller()  # any of the four roles may set the clock (PRD §2.4)
    body = get_json_body()
    iso = as_str(body, "to_iso8601")
    s = iso.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    clock.set(dt)
    return response.success({}, status=200)


# --------------------------------------------------------------------------- #
# Inn
# --------------------------------------------------------------------------- #
@app.route("/inns", methods=["POST"])
def create_inn():
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    body = get_json_body()
    name = as_str(body, "name")
    tax_bps = as_int(body, "lodging_tax_rate_bps", min_value=0)
    checkin_time = as_str(body, "checkin_time", required=False, default="15:00")
    checkout_time = as_str(body, "checkout_time", required=False, default="11:00")
    expiry_days = as_int(body, "gift_cert_expiry_days", required=False, default=365, min_value=0)
    turnover_minutes = as_int(body, "turnover_minutes", required=False, default=180, min_value=0)
    row = {
        "name": name,
        "lodging_tax_rate_bps": tax_bps,
        "checkin_time": checkin_time,
        "checkout_time": checkout_time,
        "gift_cert_expiry_days": expiry_days,
        "turnover_minutes": turnover_minutes,
    }
    stamp_create(row)
    db.inns[row["id"]] = row
    return response.success(ser.inn(row), status=201)


@app.route("/inns/<inn_id>", methods=["GET"])
def get_inn(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    inn = get_inn_or_404(inn_id)
    return response.success(ser.inn(inn), status=200)


# --------------------------------------------------------------------------- #
# Room
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/rooms", methods=["POST"])
def create_room(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    name = as_str(body, "name")
    base_rate = as_int(body, "base_rate_cents", min_value=0)
    max_occ = as_int(body, "max_occupancy", min_value=1)
    is_taxable = as_bool(body, "is_taxable", required=False, default=True)
    row = {
        "inn_id": inn_id,
        "name": name,
        "base_rate_cents": base_rate,
        "max_occupancy": max_occ,
        "is_taxable": is_taxable,
        "status": "ACTIVE",
    }
    stamp_create(row)
    db.rooms[row["id"]] = row
    return response.success(ser.room(row), status=201)


@app.route("/inns/<inn_id>/rooms", methods=["GET"])
def list_rooms(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    status = request.args.get("status")
    items = [r for r in db.rooms.values() if r["inn_id"] == inn_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.room(r) for r in window], limit, offset, total)


@app.route("/inns/<inn_id>/rooms/<room_id>", methods=["GET"])
def get_room(inn_id, room_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    room = get_scoped_or_404(db.rooms, room_id, inn_id, "Room")
    return response.success(ser.room(room), status=200)


@app.route("/inns/<inn_id>/rooms/<room_id>/retire", methods=["POST"])
def retire_room(inn_id, room_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    room = get_scoped_or_404(db.rooms, room_id, inn_id, "Room")
    body = get_json_body()
    # Optional convenience OCC guard (PRD §2.7): only checked if provided.
    expected = body.get("expected_room_version")
    if expected is not None and expected != room["version"]:
        raise err("ERR_STALE_ROOM_VERSION", "Room version mismatch")
    room["status"] = "RETIRED"
    touch(room)
    return response.success(ser.room(room), status=200)


# --------------------------------------------------------------------------- #
# RatePeriod
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/rate-periods", methods=["POST"])
def create_rate_period(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    label = as_str(body, "label")
    start_date = parse_date_field(body, "start_date")
    end_date = parse_date_field(body, "end_date")
    mult = as_int(body, "rate_multiplier_bps", min_value=0)
    min_nights = as_int(body, "min_nights", required=False, default=1, min_value=1)
    if calc.parse_date(end_date) < calc.parse_date(start_date):
        raise err("ERR_INVALID_DATE_RANGE", "end_date must be >= start_date")
    row = {
        "inn_id": inn_id,
        "label": label,
        "start_date": start_date,
        "end_date": end_date,
        "rate_multiplier_bps": mult,
        "min_nights": min_nights,
    }
    stamp_create(row)
    db.rate_periods[row["id"]] = row
    return response.success(ser.rate_period(row), status=201)


@app.route("/inns/<inn_id>/rate-periods", methods=["GET"])
def list_rate_periods(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    items = [r for r in db.rate_periods.values() if r["inn_id"] == inn_id]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.rate_period(r) for r in window], limit, offset, total)


@app.route("/inns/<inn_id>/rate-periods/<rate_period_id>", methods=["GET"])
def get_rate_period(inn_id, rate_period_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    rp = get_scoped_or_404(db.rate_periods, rate_period_id, inn_id, "RatePeriod")
    return response.success(ser.rate_period(rp), status=200)


# --------------------------------------------------------------------------- #
# Package
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/packages", methods=["POST"])
def create_package(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    name = as_str(body, "name")
    flat = as_int(body, "flat_add_cents", required=False, default=0, min_value=0)
    per_night = as_int(body, "per_night_add_cents", required=False, default=0, min_value=0)
    is_taxable = as_bool(body, "is_taxable", required=False, default=False)
    row = {
        "inn_id": inn_id,
        "name": name,
        "flat_add_cents": flat,
        "per_night_add_cents": per_night,
        "is_taxable": is_taxable,
        "status": "ACTIVE",
    }
    stamp_create(row)
    db.packages[row["id"]] = row
    return response.success(ser.package(row), status=201)


@app.route("/inns/<inn_id>/packages", methods=["GET"])
def list_packages(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    status = request.args.get("status")
    items = [p for p in db.packages.values() if p["inn_id"] == inn_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.package(p) for p in window], limit, offset, total)


@app.route("/inns/<inn_id>/packages/<package_id>", methods=["GET"])
def get_package(inn_id, package_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Housekeeper", "Guest"})
    get_inn_or_404(inn_id)
    pkg = get_scoped_or_404(db.packages, package_id, inn_id, "Package")
    return response.success(ser.package(pkg), status=200)


@app.route("/inns/<inn_id>/packages/<package_id>/retire", methods=["POST"])
def retire_package(inn_id, package_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    pkg = get_scoped_or_404(db.packages, package_id, inn_id, "Package")
    body = get_json_body()
    expected = body.get("expected_package_version")
    if expected is not None and expected != pkg["version"]:
        raise err("ERR_STALE_ROOM_VERSION", "Package version mismatch")
    pkg["status"] = "RETIRED"
    touch(pkg)
    return response.success(ser.package(pkg), status=200)


# --------------------------------------------------------------------------- #
# Guest
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/guests", methods=["POST"])
def create_guest(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    row = {
        "inn_id": inn_id,
        "full_name": full_name,
        "email": email,
    }
    stamp_create(row, common=False)
    db.guests[row["id"]] = row
    return response.success(ser.guest(row), status=201)


@app.route("/inns/<inn_id>/guests", methods=["GET"])
def list_guests(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    email = request.args.get("email")
    items = [g for g in db.guests.values() if g["inn_id"] == inn_id]
    if email is not None:
        items = [g for g in items if g["email"] == email]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.guest(g) for g in window], limit, offset, total)


@app.route("/inns/<inn_id>/guests/<guest_id>", methods=["GET"])
def get_guest(inn_id, guest_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    g = get_scoped_or_404(db.guests, guest_id, inn_id, "Guest")
    return response.success(ser.guest(g), status=200)


# --------------------------------------------------------------------------- #
# GiftCertificate
# --------------------------------------------------------------------------- #
def _next_gift_code(inn_id):
    """Server-minted redemption code, unique within an inn."""
    import secrets
    existing = {gc["code"] for gc in db.gift_certificates.values() if gc["inn_id"] == inn_id}
    while True:
        code = "GC-" + secrets.token_hex(6).upper()
        if code not in existing:
            return code


@app.route("/inns/<inn_id>/gift-certificates", methods=["POST"])
def issue_gift(inn_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper"})
    inn = get_inn_or_404(inn_id)
    body = get_json_body()
    face = as_int(body, "face_value_cents", min_value=1)
    issued = clock.today_date()
    expires = issued + timedelta(days=inn["gift_cert_expiry_days"])
    row = {
        "inn_id": inn_id,
        "code": _next_gift_code(inn_id),
        "face_value_cents": face,
        "remaining_cents": face,
        "issued_on": issued.isoformat(),
        "expires_on": expires.isoformat(),
        "status": "ACTIVE",
    }
    stamp_create(row)
    db.gift_certificates[row["id"]] = row
    return response.success(ser.gift_certificate(row), status=201)


@app.route("/inns/<inn_id>/gift-certificates", methods=["GET"])
def list_gifts(inn_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    code = request.args.get("code")
    status = request.args.get("status")
    items = [gc for gc in db.gift_certificates.values() if gc["inn_id"] == inn_id]
    if code is not None:
        items = [gc for gc in items if gc["code"] == code]
    if status is not None:
        items = [gc for gc in items if gc["status"] == status]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success(
        [ser.gift_certificate(gc) for gc in window], limit, offset, total
    )


@app.route("/inns/<inn_id>/gift-certificates/<gift_certificate_id>", methods=["GET"])
def get_gift(inn_id, gift_certificate_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    gc = get_scoped_or_404(db.gift_certificates, gift_certificate_id, inn_id, "GiftCertificate")
    return response.success(ser.gift_certificate(gc), status=200)


@app.route("/inns/<inn_id>/gift-certificates/<gift_certificate_id>/redemptions", methods=["GET"])
def list_gift_redemptions(inn_id, gift_certificate_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    gc = get_scoped_or_404(db.gift_certificates, gift_certificate_id, inn_id, "GiftCertificate")
    limit, offset = paginate_params()
    items = [
        le for le in db.ledger_entries.values()
        if le["source_kind"] == "REDEMPTION" and le.get("gift_certificate_id") == gc["id"]
    ]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.ledger_entry(le) for le in window], limit, offset, total)


@app.route("/inns/<inn_id>/gift-certificates/<gift_certificate_id>/void", methods=["POST"])
def void_gift(inn_id, gift_certificate_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager"})
    get_inn_or_404(inn_id)
    gc = get_scoped_or_404(db.gift_certificates, gift_certificate_id, inn_id, "GiftCertificate")
    body = get_json_body()
    expected = body.get("expected_gift_certificate_version")
    if expected is not None and expected != gc["version"]:
        raise err("ERR_STALE_GIFT_VERSION", "Gift certificate version mismatch")
    # PRD §3.8 / §1.2: void allowed only ACTIVE and never redeemed
    # (remaining == face). Otherwise ERR_INVALID_STATE.
    if gc["status"] != "ACTIVE" or gc["remaining_cents"] != gc["face_value_cents"]:
        raise err("ERR_INVALID_STATE", "Certificate cannot be voided")
    gc["status"] = "VOID"
    touch(gc)
    return response.success(ser.gift_certificate(gc), status=200)


# --------------------------------------------------------------------------- #
# Booking — create + reads
# --------------------------------------------------------------------------- #
def _require_booking_owner_if_guest(role, user_id, booking):
    """PRD §2.1 / validation p25: a Guest acting on a booking must own it."""
    if role == "Guest" and booking["guest_id"] != user_id:
        raise err("ERR_NOT_BOOKING_OWNER", "Guest does not own this booking")


@app.route("/inns/<inn_id>/bookings", methods=["POST"])
def create_booking(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    body = get_json_body()

    # p35 well-formedness
    room_id = as_str(body, "room_id")
    guest_id = as_str(body, "guest_id")
    package_id = as_str(body, "package_id", required=False, default=None)
    channel = as_enum(body, "channel", {"DIRECT", "OTA"})
    ota_commission_bps = as_int(body, "ota_commission_bps", required=False, default=0, min_value=0)
    checkin_date = parse_date_field(body, "checkin_date")
    checkout_date = parse_date_field(body, "checkout_date")
    guest_count = as_int(body, "guest_count", min_value=1)

    # p40 cross-inn referential integrity (FK targets must exist in this inn).
    room = db.rooms.get(room_id)
    if room is None or room["inn_id"] != inn_id:
        raise err("ERR_CROSS_INN_REFERENCE", "room_id not in this inn")
    guest = db.guests.get(guest_id)
    if guest is None or guest["inn_id"] != inn_id:
        raise err("ERR_CROSS_INN_REFERENCE", "guest_id not in this inn")
    package = None
    if package_id is not None:
        package = db.packages.get(package_id)
        if package is None or package["inn_id"] != inn_id:
            raise err("ERR_CROSS_INN_REFERENCE", "package_id not in this inn")

    # A guest creating a booking books for their own stay.
    if role == "Guest" and guest_id != request.headers.get("X-User-ID"):
        raise err("ERR_NOT_BOOKING_OWNER", "Guest may only book for themselves")

    # p50 date range
    if calc.parse_date(checkout_date) <= calc.parse_date(checkin_date):
        raise err("ERR_INVALID_DATE_RANGE", "checkout_date must be after checkin_date")

    # p55 occupancy
    if guest_count > room["max_occupancy"]:
        raise err("ERR_OCCUPANCY_EXCEEDED", "guest_count exceeds room max_occupancy")

    # p65 retirement
    if room["status"] == "RETIRED":
        raise err("ERR_RESOURCE_RETIRED", "Room is retired")
    if package is not None and package["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_RETIRED", "Package is not active")

    # p74 two-night minimum
    nights = calc.date_diff_days(checkout_date, checkin_date)
    _enforce_min_nights(inn_id, checkin_date, checkout_date, nights)

    if channel == "DIRECT":
        ota_commission_bps = 0  # forced to 0 / ignored for DIRECT (PRD §3.2)

    row = {
        "inn_id": inn_id,
        "room_id": room_id,
        "guest_id": guest_id,
        "package_id": package_id,
        "channel": channel,
        "ota_commission_bps": ota_commission_bps,
        "checkin_date": checkin_date,
        "checkout_date": checkout_date,
        "guest_count": guest_count,
        "reservation_status": "PENDING",
        "payment_status": "UNPAID",
        "refund_cents": 0,
        "cancelled_on": None,
        "remitted": False,
    }
    stamp_create(row)
    db.bookings[row["id"]] = row
    recompute_booking_money(row)
    return response.success(ser.booking(row), status=201)


def _enforce_min_nights(inn_id, checkin_date, checkout_date, nights):
    """p74: if the stay touches any night governed by a RatePeriod with
    min_nights > 1, nights must be >= the max such min_nights across touched periods.
    """
    rate_periods = [rp for rp in db.rate_periods.values() if rp["inn_id"] == inn_id]
    required = 1
    for night in calc.occupied_nights(checkin_date, checkout_date):
        for rp in rate_periods:
            if calc.parse_date(rp["start_date"]) <= night <= calc.parse_date(rp["end_date"]):
                if rp["min_nights"] > required:
                    required = rp["min_nights"]
    if nights < required:
        raise err("ERR_MIN_NIGHTS_NOT_MET", "Stay does not meet minimum nights of %d" % required)


@app.route("/inns/<inn_id>/bookings", methods=["GET"])
def list_bookings(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    items = [b for b in db.bookings.values() if b["inn_id"] == inn_id]
    for key in ("room_id", "guest_id", "package_id"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b.get(key) == val]
    rstatus = request.args.get("reservation_status")
    if rstatus is not None:
        items = [b for b in items if b["reservation_status"] == rstatus]
    channel = request.args.get("channel")
    if channel is not None:
        items = [b for b in items if b["channel"] == channel]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.booking(b) for b in window], limit, offset, total)


@app.route("/inns/<inn_id>/bookings/<booking_id>", methods=["GET"])
def get_booking(inn_id, booking_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    b = get_booking_scoped_or_404(booking_id, inn_id)
    return response.success(ser.booking(b), status=200)


# --------------------------------------------------------------------------- #
# Booking — money: pay-deposit, redeem-gift, refund-quote
# --------------------------------------------------------------------------- #
def _append_ledger(booking_id, source_kind, amount_cents, gift_certificate_id=None):
    row = {
        "booking_id": booking_id,
        "source_kind": source_kind,
        "gift_certificate_id": gift_certificate_id,
        "amount_cents": amount_cents,
        "occurred_on": clock.today_iso(),
    }
    stamp_create(row, common=False)
    db.ledger_entries[row["id"]] = row
    return row


@app.route("/inns/<inn_id>/bookings/<booking_id>/pay-deposit", methods=["POST"])
def pay_deposit(inn_id, booking_id):
    user_id, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)
    _require_booking_owner_if_guest(role, user_id, booking)
    body = get_json_body()
    amount = as_int(body, "amount_cents")
    # p76: amount >= 1 and amount <= total - deposit_paid.
    outstanding = booking["total_cents"] - booking["deposit_paid_cents"]
    if amount < 1 or amount > outstanding:
        raise err("ERR_PAYMENT_EXCEEDS_BALANCE", "Payment would overpay the booking")
    _append_ledger(booking_id, "DEPOSIT", amount)
    recompute_payment_fields(booking)
    touch(booking)
    return response.success(ser.booking(booking), status=200)


@app.route("/inns/<inn_id>/bookings/<booking_id>/redeem-gift", methods=["POST"])
def redeem_gift(inn_id, booking_id):
    user_id, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)
    _require_booking_owner_if_guest(role, user_id, booking)
    body = get_json_body()
    gift_id = as_str(body, "gift_certificate_id")
    amount = as_int(body, "amount_cents")
    expected_version = as_int(body, "expected_gift_certificate_version")

    # p40 cross-inn FK on the gift certificate.
    gc = db.gift_certificates.get(gift_id)
    if gc is None or gc["inn_id"] != inn_id:
        raise err("ERR_CROSS_INN_REFERENCE", "gift_certificate_id not in this inn")

    # p90 OCC on the gift certificate version (mandatory for redeem-gift).
    if expected_version != gc["version"]:
        raise err("ERR_STALE_GIFT_VERSION", "Gift certificate version mismatch")

    # p78 gift sufficiency: amount>=1, <= min(remaining, owed); ACTIVE & not expired.
    owed = booking["total_cents"] - booking["deposit_paid_cents"]
    expired = clock.today_date() >= calc.parse_date(gc["expires_on"])
    if (
        amount < 1
        or gc["status"] != "ACTIVE"
        or expired
        or amount > gc["remaining_cents"]
        or amount > owed
    ):
        raise err("ERR_GIFT_INSUFFICIENT", "Redemption not permitted")

    _append_ledger(booking_id, "REDEMPTION", amount, gift_certificate_id=gift_id)
    gc["remaining_cents"] -= amount
    if gc["remaining_cents"] == 0:
        gc["status"] = "DEPLETED"
    touch(gc)
    recompute_payment_fields(booking)
    touch(booking)
    return response.success(ser.booking(booking), status=200)


@app.route("/inns/<inn_id>/bookings/<booking_id>/refund-quote", methods=["GET"])
def refund_quote(inn_id, booking_id):
    user_id, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)
    _require_booking_owner_if_guest(role, user_id, booking)
    # Provisional variant: days_before measured from today's logical clock.
    days_before = (calc.parse_date(booking["checkin_date"]) - clock.today_date()).days
    if days_before < 0:
        days_before = 0
    quote = calc.compute_cancellation_refund(
        booking["channel"], booking["deposit_paid_cents"], days_before
    )
    snapshot = dict(booking)
    snapshot["refund_cents"] = quote
    return response.success(ser.booking(snapshot), status=200)


# --------------------------------------------------------------------------- #
# Booking — reservation lifecycle
# --------------------------------------------------------------------------- #
def _room_interval_overlaps(room_id, checkin_date, checkout_date, exclude_booking_id):
    """Half-open [checkin, checkout) overlap against other CONFIRMED/CHECKED_IN
    bookings on the same room (p70)."""
    s1 = calc.parse_date(checkin_date)
    e1 = calc.parse_date(checkout_date)
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id or b["room_id"] != room_id:
            continue
        if b["reservation_status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        s2 = calc.parse_date(b["checkin_date"])
        e2 = calc.parse_date(b["checkout_date"])
        # half-open overlap: s1 < e2 and s2 < e1
        if s1 < e2 and s2 < e1:
            return True
    return False


@app.route("/inns/<inn_id>/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(inn_id, booking_id):
    user_id, role = get_caller()
    require_role(role, {"Guest", "Innkeeper"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)
    _require_booking_owner_if_guest(role, user_id, booking)
    body = get_json_body()
    expected_room_version = as_int(body, "expected_room_version")

    # p60 state guard
    if booking["reservation_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Booking is not PENDING")

    room = db.rooms[booking["room_id"]]

    # Recompute money as of confirm (PRD §3.2).
    recompute_booking_money(booking)

    # p70 double-booking (before deposit coverage p80).
    if _room_interval_overlaps(
        room["id"], booking["checkin_date"], booking["checkout_date"], booking["id"]
    ):
        raise err("ERR_ROOM_DOUBLE_BOOKED", "Room night interval overlaps an existing booking")

    # p80 deposit coverage
    if booking["deposit_paid_cents"] < booking["deposit_due_cents"]:
        raise err("ERR_DEPOSIT_NOT_MET", "Deposit not fully covered")

    # Confirmation also requires the room ACTIVE (PRD §3.4).
    if room["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Room is not active")

    # p90 OCC on room version (mandatory for confirm).
    if expected_room_version != room["version"]:
        raise err("ERR_STALE_ROOM_VERSION", "Room version mismatch")

    booking["reservation_status"] = "CONFIRMED"
    booking["payment_status"] = "DEPOSIT_HELD"
    touch(booking)
    touch(room)  # increments Room.version by 1
    return response.success(ser.booking(booking), status=200)


@app.route("/inns/<inn_id>/bookings/<booking_id>/check-in", methods=["POST"])
def check_in_booking(inn_id, booking_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)

    if booking["reservation_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Booking is not CONFIRMED")
    # logical clock date >= checkin_date
    if clock.today_date() < calc.parse_date(booking["checkin_date"]):
        raise err("ERR_INVALID_STATE", "Check-in date not yet reached")

    # p72 turnover gate: most recent non-SKIPPED housekeeping task for the room
    # must be DONE and ready_after <= now. No task at all -> fresh room, allowed.
    if not _turnover_satisfied(booking["room_id"]):
        raise err("ERR_TURNOVER_NOT_READY", "Room turnover not yet ready")

    booking["reservation_status"] = "CHECKED_IN"
    touch(booking)
    return response.success(ser.booking(booking), status=200)


def _turnover_satisfied(room_id):
    tasks = [t for t in db.housekeeping_tasks.values() if t["room_id"] == room_id]
    non_skipped = [t for t in tasks if t["status"] != "SKIPPED"]
    if not non_skipped:
        return True  # fresh room or all prior turnover skipped
    # Most recent non-SKIPPED task by creation order.
    latest = max(non_skipped, key=lambda t: (t["created_at"], t["_seq"]))
    if latest["status"] != "DONE":
        return False
    ready_after = _parse_iso(latest["ready_after"])
    return ready_after <= clock.now()


def _parse_iso(s):
    """Parse an ISO 8601 instant, tolerating a trailing 'Z' on Python 3.9."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@app.route("/inns/<inn_id>/bookings/<booking_id>/check-out", methods=["POST"])
def check_out_booking(inn_id, booking_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)

    if booking["reservation_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Booking is not CHECKED_IN")

    room = db.rooms[booking["room_id"]]
    booking["reservation_status"] = "CHECKED_OUT"
    booking["payment_status"] = "SETTLED"

    # Cascade hop 1: spawn a PENDING housekeeping task.
    inn = db.inns[inn_id]
    ready_after = clock.now() + timedelta(minutes=inn["turnover_minutes"])
    task = {
        "booking_id": booking_id,
        "room_id": room["id"],
        "ready_after": _iso_z(ready_after),
        "status": "PENDING",
    }
    stamp_create(task)
    db.housekeeping_tasks[task["id"]] = task

    touch(booking)
    touch(room)  # increments Room.version by 1
    return response.success(ser.booking(booking), status=200)


def _iso_z(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@app.route("/inns/<inn_id>/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(inn_id, booking_id):
    user_id, role = get_caller()
    require_role(role, {"Guest", "Innkeeper"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)
    _require_booking_owner_if_guest(role, user_id, booking)

    if booking["reservation_status"] not in ("PENDING", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Booking cannot be cancelled from its current state")

    cancelled_on = clock.today_date()
    booking["cancelled_on"] = cancelled_on.isoformat()
    days_before = (calc.parse_date(booking["checkin_date"]) - cancelled_on).days
    if days_before < 0:
        days_before = 0
    refund = calc.compute_cancellation_refund(
        booking["channel"], booking["deposit_paid_cents"], days_before
    )
    booking["refund_cents"] = refund
    booking["reservation_status"] = "CANCELLED"

    deposit_paid = booking["deposit_paid_cents"]
    if refund > 0:
        # Waterfall: cash bucket first, then gift bucket (PRD §3.5).
        _apply_refund_waterfall(booking, refund)
        booking["payment_status"] = "REFUNDED"
    elif deposit_paid > 0:
        _append_ledger(booking_id, "FORFEIT", 0)
        booking["payment_status"] = "FORFEITED"
    # If refund == 0 and nothing was paid, payment_status stays as-is (UNPAID/DEPOSIT_HELD).
    # PRD only specifies FORFEITED when deposit_paid_cents > 0.

    recompute_payment_fields(booking)

    # Cascade: release room interval (bump version), cancel breakfast plan.
    room = db.rooms[booking["room_id"]]
    touch(room)
    _cascade_cancel_breakfast(booking_id)

    touch(booking)
    return response.success(ser.booking(booking), status=200)


def _apply_refund_waterfall(booking, refund):
    """PRD §3.5 / calc gift_restore_on_cancel: cash bucket fills first, gift bucket
    gets the remainder. cash_deposit = sum of DEPOSIT entries; gift remainder is
    restored to the certificate's remaining_cents.
    """
    cash_deposit = sum(
        le["amount_cents"] for le in db.ledger_entries.values()
        if le["booking_id"] == booking["id"] and le["source_kind"] == "DEPOSIT"
    )
    cash_refund = min(refund, cash_deposit)
    gift_restore = refund - cash_refund

    # Cash bucket: a single negative REFUND ledger entry for the refunded cash.
    if cash_refund > 0:
        _append_ledger(booking["id"], "REFUND", -cash_refund)
    else:
        # refund_cents > 0 but it all flows to gift: still record the negative
        # REFUND for the gift-restored portion so payment_status->REFUNDED has a row.
        # PRD §3.5 says "appends a REFUND ledger entry carrying the negative refund
        # amount" whenever refund_cents > 0.
        pass

    if gift_restore > 0:
        # Restore to the most-recently-redeemed certificate(s) for this booking.
        # Pinned order: most recent redemption first (LIFO), restoring up to each
        # redemption's amount. Single-cert is the common case.
        redemptions = sorted(
            [
                le for le in db.ledger_entries.values()
                if le["booking_id"] == booking["id"] and le["source_kind"] == "REDEMPTION"
            ],
            key=lambda le: (le["created_at"], le["_seq"]),
            reverse=True,
        )
        remaining_to_restore = gift_restore
        for le in redemptions:
            if remaining_to_restore <= 0:
                break
            gc = db.gift_certificates.get(le["gift_certificate_id"])
            if gc is None:
                continue
            portion = min(remaining_to_restore, le["amount_cents"])
            gc["remaining_cents"] += portion
            remaining_to_restore -= portion
            if (
                gc["status"] == "DEPLETED"
                and gc["remaining_cents"] > 0
                and clock.today_date() < calc.parse_date(gc["expires_on"])
            ):
                gc["status"] = "ACTIVE"
            touch(gc)
        # Record the full refund (cash+gift) as a single negative REFUND entry
        # when there was no cash refund row above.
        if cash_refund == 0:
            _append_ledger(booking["id"], "REFUND", -gift_restore)


def _cascade_cancel_breakfast(booking_id):
    for bp in db.breakfast_plans.values():
        if bp["booking_id"] == booking_id and bp["status"] in ("REQUESTED", "CONFIRMED"):
            bp["status"] = "CANCELLED"
            touch(bp)


@app.route("/inns/<inn_id>/bookings/<booking_id>/mark-no-show", methods=["POST"])
def mark_no_show(inn_id, booking_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    booking = get_booking_scoped_or_404(booking_id, inn_id)

    if booking["reservation_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Booking is not CONFIRMED")
    # logical clock date > checkin_date (arrival night fully passed).
    if clock.today_date() <= calc.parse_date(booking["checkin_date"]):
        raise err("ERR_INVALID_STATE", "Booking is not yet no-show-eligible")

    booking["reservation_status"] = "NO_SHOW"
    booking["payment_status"] = "FORFEITED"
    _append_ledger(booking_id, "FORFEIT", 0)
    recompute_payment_fields(booking)

    room = db.rooms[booking["room_id"]]
    touch(room)
    _cascade_cancel_breakfast(booking_id)

    touch(booking)
    return response.success(ser.booking(booking), status=200)


# --------------------------------------------------------------------------- #
# Booking ledger reads
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/bookings/<booking_id>/ledger", methods=["GET"])
def list_booking_ledger(inn_id, booking_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    get_booking_scoped_or_404(booking_id, inn_id)
    limit, offset = paginate_params()
    items = [le for le in db.ledger_entries.values() if le["booking_id"] == booking_id]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.ledger_entry(le) for le in window], limit, offset, total)


def _booking_ids_for_inn(inn_id):
    return {b["id"] for b in db.bookings.values() if b["inn_id"] == inn_id}


@app.route("/inns/<inn_id>/payment-ledger-entries", methods=["GET"])
def list_ledger_entries(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    inn_booking_ids = _booking_ids_for_inn(inn_id)
    items = [le for le in db.ledger_entries.values() if le["booking_id"] in inn_booking_ids]
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [le for le in items if le["booking_id"] == booking_id]
    gift_id = request.args.get("gift_certificate_id")
    if gift_id is not None:
        items = [le for le in items if le.get("gift_certificate_id") == gift_id]
    source_kind = request.args.get("source_kind")
    if source_kind is not None:
        items = [le for le in items if le["source_kind"] == source_kind]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.ledger_entry(le) for le in window], limit, offset, total)


@app.route("/inns/<inn_id>/payment-ledger-entries/<payment_ledger_entry_id>", methods=["GET"])
def get_ledger_entry(inn_id, payment_ledger_entry_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "FinanceManager", "Guest"})
    get_inn_or_404(inn_id)
    le = db.ledger_entries.get(payment_ledger_entry_id)
    if le is None or le["booking_id"] not in _booking_ids_for_inn(inn_id):
        raise err("ERR_NOT_FOUND", "Ledger entry not found")
    return response.success(ser.ledger_entry(le), status=200)


# --------------------------------------------------------------------------- #
# BreakfastPlan
# --------------------------------------------------------------------------- #
@app.route("/inns/<inn_id>/breakfast-plans", methods=["POST"])
def create_breakfast_plan(inn_id):
    user_id, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    booking_id = as_str(body, "booking_id")
    party_size = as_int(body, "party_size", min_value=1)
    dietary_flags = body.get("dietary_flags", [])
    if dietary_flags is None:
        dietary_flags = []
    if not isinstance(dietary_flags, list) or any(f not in DIETARY_FLAGS for f in dietary_flags):
        raise err("ERR_INVALID_REQUEST", "dietary_flags must be a subset of the allowed flags")
    # VEGAN implies VEGETARIAN.
    flags = set(dietary_flags)
    if "VEGAN" in flags:
        flags.add("VEGETARIAN")

    booking = db.bookings.get(booking_id)
    if booking is None or booking["inn_id"] != inn_id:
        raise err("ERR_NOT_FOUND", "Booking not found")
    _require_booking_owner_if_guest(role, user_id, booking)

    # p68 party_size <= booking.guest_count
    if party_size > booking["guest_count"]:
        raise err("ERR_BREAKFAST_OVER_PARTY", "party_size exceeds booking guest_count")

    row = {
        "booking_id": booking_id,
        "party_size": party_size,
        "dietary_flags": sorted(flags),
        "status": "REQUESTED",
    }
    stamp_create(row)
    db.breakfast_plans[row["id"]] = row
    return response.success(ser.breakfast_plan(row), status=201)


def _breakfast_in_inn(bp, inn_id):
    booking = db.bookings.get(bp["booking_id"])
    return booking is not None and booking["inn_id"] == inn_id


def _get_breakfast_scoped(bp_id, inn_id):
    bp = db.breakfast_plans.get(bp_id)
    if bp is None or not _breakfast_in_inn(bp, inn_id):
        raise err("ERR_NOT_FOUND", "Breakfast plan not found")
    return bp


@app.route("/inns/<inn_id>/breakfast-plans", methods=["GET"])
def list_breakfast_plans(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    items = [bp for bp in db.breakfast_plans.values() if _breakfast_in_inn(bp, inn_id)]
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [bp for bp in items if bp["booking_id"] == booking_id]
    status = request.args.get("status")
    if status is not None:
        items = [bp for bp in items if bp["status"] == status]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.breakfast_plan(bp) for bp in window], limit, offset, total)


@app.route("/inns/<inn_id>/breakfast-plans/<breakfast_plan_id>", methods=["GET"])
def get_breakfast_plan(inn_id, breakfast_plan_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    bp = _get_breakfast_scoped(breakfast_plan_id, inn_id)
    return response.success(ser.breakfast_plan(bp), status=200)


@app.route("/inns/<inn_id>/breakfast-plans/<breakfast_plan_id>/confirm", methods=["POST"])
def confirm_breakfast_plan(inn_id, breakfast_plan_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    bp = _get_breakfast_scoped(breakfast_plan_id, inn_id)
    if bp["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Breakfast plan is not REQUESTED")
    booking = db.bookings.get(bp["booking_id"])
    if booking is None or booking["reservation_status"] not in ("CONFIRMED", "CHECKED_IN"):
        raise err("ERR_INVALID_STATE", "Parent booking is not live")
    bp["status"] = "CONFIRMED"
    touch(bp)
    return response.success(ser.breakfast_plan(bp), status=200)


@app.route("/inns/<inn_id>/breakfast-plans/<breakfast_plan_id>/cancel", methods=["POST"])
def cancel_breakfast_plan(inn_id, breakfast_plan_id):
    user_id, role = get_caller()
    require_role(role, {"Innkeeper", "Guest"})
    get_inn_or_404(inn_id)
    bp = _get_breakfast_scoped(breakfast_plan_id, inn_id)
    if role == "Guest":
        booking = db.bookings.get(bp["booking_id"])
        if booking is not None and booking["guest_id"] != user_id:
            raise err("ERR_NOT_BOOKING_OWNER", "Guest does not own this booking")
    if bp["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Breakfast plan cannot be cancelled")
    bp["status"] = "CANCELLED"
    touch(bp)
    return response.success(ser.breakfast_plan(bp), status=200)


# --------------------------------------------------------------------------- #
# HousekeepingTask
# --------------------------------------------------------------------------- #
def _task_in_inn(task, inn_id):
    room = db.rooms.get(task["room_id"])
    return room is not None and room["inn_id"] == inn_id


def _get_task_scoped(task_id, inn_id):
    task = db.housekeeping_tasks.get(task_id)
    if task is None or not _task_in_inn(task, inn_id):
        raise err("ERR_NOT_FOUND", "Housekeeping task not found")
    return task


@app.route("/inns/<inn_id>/housekeeping-tasks", methods=["GET"])
def list_housekeeping_tasks(inn_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Housekeeper"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    items = [t for t in db.housekeeping_tasks.values() if _task_in_inn(t, inn_id)]
    booking_id = request.args.get("booking_id")
    if booking_id is not None:
        items = [t for t in items if t["booking_id"] == booking_id]
    room_id = request.args.get("room_id")
    if room_id is not None:
        items = [t for t in items if t["room_id"] == room_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.housekeeping_task(t) for t in window], limit, offset, total)


@app.route("/inns/<inn_id>/housekeeping-tasks/<housekeeping_task_id>", methods=["GET"])
def get_housekeeping_task(inn_id, housekeeping_task_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper", "Housekeeper"})
    get_inn_or_404(inn_id)
    task = _get_task_scoped(housekeeping_task_id, inn_id)
    return response.success(ser.housekeeping_task(task), status=200)


@app.route("/inns/<inn_id>/housekeeping-tasks/<housekeeping_task_id>/start", methods=["POST"])
def start_housekeeping(inn_id, housekeeping_task_id):
    _, role = get_caller()
    require_role(role, {"Housekeeper"})
    get_inn_or_404(inn_id)
    task = _get_task_scoped(housekeeping_task_id, inn_id)
    if task["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Task is not PENDING")
    task["status"] = "IN_PROGRESS"
    touch(task)
    return response.success(ser.housekeeping_task(task), status=200)


@app.route("/inns/<inn_id>/housekeeping-tasks/<housekeeping_task_id>/complete", methods=["POST"])
def complete_housekeeping(inn_id, housekeeping_task_id):
    _, role = get_caller()
    require_role(role, {"Housekeeper"})
    get_inn_or_404(inn_id)
    task = _get_task_scoped(housekeeping_task_id, inn_id)
    if task["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Task is not IN_PROGRESS")
    task["status"] = "DONE"
    touch(task)
    return response.success(ser.housekeeping_task(task), status=200)


@app.route("/inns/<inn_id>/housekeeping-tasks/<housekeeping_task_id>/skip", methods=["POST"])
def skip_housekeeping(inn_id, housekeeping_task_id):
    _, role = get_caller()
    require_role(role, {"Innkeeper"})
    get_inn_or_404(inn_id)
    task = _get_task_scoped(housekeeping_task_id, inn_id)
    if task["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Task is not PENDING")
    task["status"] = "SKIPPED"
    touch(task)
    return response.success(ser.housekeeping_task(task), status=200)


# --------------------------------------------------------------------------- #
# TaxRemittance
# --------------------------------------------------------------------------- #
def _sweep_pool(inn_id, period_start, period_end, variant):
    ps = calc.parse_date(period_start)
    pe = calc.parse_date(period_end)
    pool = []
    for b in db.bookings.values():
        if b["inn_id"] != inn_id or b["remitted"]:
            continue
        co = calc.parse_date(b["checkout_date"])
        if not (ps <= co <= pe):
            continue
        if variant == "ESTIMATED":
            if b["reservation_status"] in ("CONFIRMED", "CHECKED_IN", "CHECKED_OUT"):
                pool.append(b)
        else:  # FINAL
            if b["reservation_status"] == "CHECKED_OUT":
                pool.append(b)
    return pool


@app.route("/inns/<inn_id>/tax-remittances", methods=["POST"])
def create_tax_remittance(inn_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager"})
    get_inn_or_404(inn_id)
    body = get_json_body()
    period_start = parse_date_field(body, "period_start")
    period_end = parse_date_field(body, "period_end")
    variant = as_enum(body, "variant", {"ESTIMATED", "FINAL"})
    if calc.parse_date(period_end) < calc.parse_date(period_start):
        raise err("ERR_INVALID_DATE_RANGE", "period_end must be >= period_start")

    pool = _sweep_pool(inn_id, period_start, period_end, variant)
    swept_count = len(pool)
    tax_total = sum(b["lodging_tax_cents"] for b in pool)
    row = {
        "inn_id": inn_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "swept_booking_count": swept_count,
        "tax_total_cents": tax_total,
        "status": "OPEN",
        # PRD §3.9: "At open time the system records ... the number of bookings in
        # the pool"; the swept SET is fixed at open. Filing later checks/stamps
        # "every booking in the swept set", so we freeze the booking ids here
        # rather than re-resolving the pool at file time (a re-resolve would drop
        # an already-remitted booking and make ERR_ALREADY_REMITTED unreachable).
        "_swept_booking_ids": [b["id"] for b in pool],
    }
    stamp_create(row)
    db.tax_remittances[row["id"]] = row
    return response.success(ser.tax_remittance(row), status=201)


@app.route("/inns/<inn_id>/tax-remittances", methods=["GET"])
def list_tax_remittances(inn_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper"})
    get_inn_or_404(inn_id)
    limit, offset = paginate_params()
    items = [t for t in db.tax_remittances.values() if t["inn_id"] == inn_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    variant = request.args.get("variant")
    if variant is not None:
        items = [t for t in items if t["variant"] == variant]
    window, total = sort_and_page(items, limit, offset)
    return response.list_success([ser.tax_remittance(t) for t in window], limit, offset, total)


@app.route("/inns/<inn_id>/tax-remittances/<tax_remittance_id>", methods=["GET"])
def get_tax_remittance(inn_id, tax_remittance_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager", "Innkeeper"})
    get_inn_or_404(inn_id)
    t = get_scoped_or_404(db.tax_remittances, tax_remittance_id, inn_id, "TaxRemittance")
    return response.success(ser.tax_remittance(t), status=200)


@app.route("/inns/<inn_id>/tax-remittances/<tax_remittance_id>/file", methods=["POST"])
def file_tax_remittance(inn_id, tax_remittance_id):
    _, role = get_caller()
    require_role(role, {"FinanceManager"})
    get_inn_or_404(inn_id)
    t = get_scoped_or_404(db.tax_remittances, tax_remittance_id, inn_id, "TaxRemittance")
    body = get_json_body()
    expected = body.get("expected_tax_remittance_version")
    if expected is not None and expected != t["version"]:
        raise err("ERR_STALE_ROOM_VERSION", "TaxRemittance version mismatch")

    if t["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Remittance is not OPEN")

    # PRD §3.9: file against the swept set frozen at open time, not a fresh sweep.
    pool = [db.bookings[bid] for bid in t.get("_swept_booking_ids", []) if bid in db.bookings]
    if any(b["remitted"] for b in pool):
        raise err("ERR_ALREADY_REMITTED", "A swept booking is already remitted")

    # Freeze totals at filed values and stamp remitted=true on every swept booking.
    t["swept_booking_count"] = len(pool)
    t["tax_total_cents"] = sum(b["lodging_tax_cents"] for b in pool)
    t["status"] = "FILED"
    for b in pool:
        b["remitted"] = True
        touch(b)
    touch(t)
    return response.success(ser.tax_remittance(t), status=200)


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
@app.route("/", methods=["GET"])
def root():
    return response.success({}, status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Silence Werkzeug per-request logging and the dev-server banner: under
    # per-test-server isolation the server cold-boots before every test, and with
    # many rounds running concurrently this logging is pure boot-time overhead.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
