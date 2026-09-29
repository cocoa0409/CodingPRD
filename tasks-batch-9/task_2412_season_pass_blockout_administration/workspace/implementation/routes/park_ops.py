"""Reservations and gate visits."""

from datetime import timedelta

from flask import Blueprint

import serializers
from db import db, parse_day, parse_instant
from errors import ApiError
from middleware import (ROLE_COMPLIANCE_OFFICER, ROLE_GATE_AGENT, ROLE_PASS_OFFICE_CLERK,
                        ROLE_PASSHOLDER, ROLE_PROGRAM_ADMIN, require)
from response import created_response, list_response, object_response
from services import calc, domain
from validate import field, invalid, pagination, query_enum, query_string, read_body

bp = Blueprint("park_ops", __name__)

RESERVATION_STATUSES = (
    "CONFIRMED",
    "REDEEMED",
    "CANCELLED_BY_HOLDER",
    "CANCELLED_BY_SUSPENSION",
    "CANCELLED_BY_BLOCKOUT",
    "NO_SHOW",
)
VISIT_STATUSES = ("OPEN", "CLOSED")
GATE_CODES = ("NORTH", "SOUTH", "EAST", "WEST")
PHOTO_MATCHES = ("MATCH", "MISMATCH", "NOT_CHECKED")

RESERVATION_PROGRAM_STATUSES = ("SEASON_ACTIVE", "RENEWAL_OPEN")

WINDOW_OPEN = "08:00"
WINDOW_CLOSE = "22:00"

ALL_READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_PASS_OFFICE_CLERK,
    ROLE_GATE_AGENT,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PASSHOLDER,
)


def _minutes(text):
    hours, minutes = text.split(":")
    return int(hours) * 60 + int(minutes)


def _overlaps(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


# ------------------------------------------------------------- reservations
@bp.post("/reservations")
def create_reservation():
    user_id, role = require(ROLE_PASS_OFFICE_CLERK, ROLE_PASSHOLDER)
    body = read_body({
        "season_pass_id": field("string", required=True),
        "park_day_id": field("string", required=True),
        "arrival_window_start": field("time", required=True),
        "arrival_window_end": field("time", required=True),
    })
    if body["arrival_window_start"] < WINDOW_OPEN:
        raise invalid("arrival_window_start must be at or after 08:00")
    if body["arrival_window_end"] > WINDOW_CLOSE:
        raise invalid("arrival_window_end must be at or before 22:00")

    park_day = domain.get_park_day(body["park_day_id"])
    season_pass = domain.get_pass(body["season_pass_id"])

    if role == ROLE_PASSHOLDER and season_pass["passholder_id"] != user_id:
        raise ApiError("ERR_NOT_PASS_OWNER")
    program = domain.get_program(season_pass["program_id"])
    if program["status"] not in RESERVATION_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    if season_pass["pass_status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE")
    if season_pass["billing_status"] in ("DELINQUENT", "DEFAULTED"):
        raise ApiError("ERR_PASS_BILLING_NOT_CURRENT")
    if park_day["day_class"] == "CAPACITY_LOCKED":
        raise ApiError("ERR_PARK_DAY_CAPACITY_LOCKED")
    if park_day["program_id"] != season_pass["program_id"]:
        raise ApiError("ERR_PARK_DAY_PROGRAM_MISMATCH")
    if parse_day(park_day["calendar_date"]) < db.today():
        raise ApiError("ERR_PARK_DAY_IN_PAST")
    start = _minutes(body["arrival_window_start"])
    end = _minutes(body["arrival_window_end"])
    if end <= start:
        raise ApiError("ERR_ARRIVAL_WINDOW_INVALID")
    if domain.has_active_blockout(season_pass["tier_id"], park_day["id"]):
        raise ApiError("ERR_BLOCKOUT_DATE")

    own = domain.pass_reservations(season_pass["id"])
    for reservation in own:
        if reservation["park_day_id"] == park_day["id"] and reservation["status"] in (
            "CONFIRMED", "REDEEMED",
        ):
            raise ApiError("ERR_DUPLICATE_RESERVATION")

    tier = domain.get_tier(season_pass["tier_id"])
    today = db.today()
    peak_held = 0
    for reservation in own:
        if reservation["status"] != "CONFIRMED":
            continue
        day = db.park_days.get(reservation["park_day_id"])
        if day is None:
            continue
        if day["day_class"] in ("PEAK", "CAPACITY_LOCKED") and parse_day(day["calendar_date"]) >= today:
            peak_held += 1
    if peak_held >= tier["peak_reservation_quota"]:
        raise ApiError("ERR_RESERVATION_QUOTA_EXCEEDED")

    counters = domain.day_counters(park_day)
    if counters["reserved_count"] >= park_day["reservation_slot_capacity"]:
        raise ApiError("ERR_PARK_DAY_CAPACITY_FULL")

    overlapping = 0
    for reservation in domain.day_reservations(park_day["id"]):
        if reservation["status"] != "CONFIRMED":
            continue
        if _overlaps(
            _minutes(reservation["arrival_window_start"]),
            _minutes(reservation["arrival_window_end"]),
            start,
            end,
        ):
            overlapping += 1
    if overlapping >= park_day["window_slot_capacity"]:
        raise ApiError("ERR_RESERVATION_SLOT_FULL")

    record = db.insert("reservations", {
        "season_pass_id": season_pass["id"],
        "park_day_id": park_day["id"],
        "arrival_window_start": body["arrival_window_start"],
        "arrival_window_end": body["arrival_window_end"],
        "status": "CONFIRMED",
        "redeemed_visit_id": None,
    })
    park_day["grant_count"] += 1
    db.commit()
    return created_response(serializers.reservation_out(record))


@bp.get("/reservations")
def list_reservations():
    require(*ALL_READ_ROLES)
    limit, offset = pagination()
    season_pass_id = query_string("season_pass_id")
    park_day_id = query_string("park_day_id")
    status = query_enum("status", RESERVATION_STATUSES)
    redeemed_visit_id = query_string("redeemed_visit_id")
    rows = db.rows("reservations")
    if season_pass_id is not None:
        rows = [r for r in rows if r["season_pass_id"] == season_pass_id]
    if park_day_id is not None:
        rows = [r for r in rows if r["park_day_id"] == park_day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if redeemed_visit_id is not None:
        rows = [r for r in rows if r["redeemed_visit_id"] == redeemed_visit_id]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.reservation_out(r) for r in rows], limit, offset)


@bp.get("/reservations/<reservation_id>")
def get_reservation(reservation_id):
    require(*ALL_READ_ROLES)
    return object_response(serializers.reservation_out(domain.get_reservation(reservation_id)))


@bp.post("/reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    user_id, role = require(ROLE_PASS_OFFICE_CLERK, ROLE_PASSHOLDER)
    read_body({})
    reservation = domain.get_reservation(reservation_id)
    season_pass = db.season_passes.get(reservation["season_pass_id"])
    if role == ROLE_PASSHOLDER and (
        season_pass is None or season_pass["passholder_id"] != user_id
    ):
        raise ApiError("ERR_NOT_PASS_OWNER")
    if reservation["status"] != "CONFIRMED":
        raise ApiError("ERR_RESERVATION_NOT_CANCELLABLE")
    reservation["status"] = "CANCELLED_BY_HOLDER"
    db.commit()
    return object_response(serializers.reservation_out(reservation))


# -------------------------------------------------------------------- visits
@bp.post("/visits")
def create_visit():
    require(ROLE_GATE_AGENT)
    body = read_body({
        "season_pass_id": field("string", required=True),
        "park_day_id": field("string", required=True),
        "entry_at": field("datetime", required=True),
        "gate_code": field("enum", required=True, enum=GATE_CODES),
        "photo_match": field("enum", enum=PHOTO_MATCHES),
    })
    park_day = domain.get_park_day(body["park_day_id"])
    season_pass = domain.get_pass(body["season_pass_id"])
    program = domain.get_program(season_pass["program_id"])
    entry_at = parse_instant(body["entry_at"])

    if not season_pass["photo_captured"] or not season_pass["identity_bound"]:
        raise ApiError("ERR_PHOTO_NOT_CAPTURED")
    if program["status"] not in RESERVATION_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    if season_pass["pass_status"] != "ACTIVE":
        raise ApiError("ERR_PASS_NOT_ACTIVE")
    holder = domain.get_passholder(season_pass["passholder_id"])
    if domain.pass_under_hold(season_pass["id"]) or holder["status"] == "BANNED":
        raise ApiError("ERR_PASS_TRANSFER_PROHIBITED")
    limit_instant = entry_at - timedelta(minutes=calc.ANTIPASSBACK_MINUTES)
    for visit in domain.pass_visits(season_pass["id"]):
        previous = parse_instant(visit["entry_at"])
        if limit_instant <= previous <= entry_at:
            raise ApiError("ERR_ANTIPASSBACK_VIOLATION")
    if park_day["program_id"] != season_pass["program_id"]:
        raise ApiError("ERR_PARK_DAY_PROGRAM_MISMATCH")
    if entry_at.date() != parse_day(park_day["calendar_date"]):
        raise ApiError("ERR_ENTRY_DATE_MISMATCH")
    if domain.has_active_blockout(season_pass["tier_id"], park_day["id"]):
        raise ApiError("ERR_BLOCKOUT_DATE")

    tier = domain.get_tier(season_pass["tier_id"])
    confirmed = [
        r for r in domain.pass_reservations(season_pass["id"])
        if r["park_day_id"] == park_day["id"] and r["status"] == "CONFIRMED"
    ]
    if (
        park_day["day_class"] in ("PEAK", "CAPACITY_LOCKED")
        and tier["reservation_required_on_peak"]
        and not confirmed
    ):
        raise ApiError("ERR_RESERVATION_REQUIRED")

    record = db.insert("visits", {
        "season_pass_id": season_pass["id"],
        "park_day_id": park_day["id"],
        "reservation_id": None,
        "entry_at": body["entry_at"],
        "gate_code": body["gate_code"],
        "photo_match": body.get("photo_match", "NOT_CHECKED"),
        "status": "OPEN",
        "spend_cents": 0,
        "discount_applied_pct": tier["in_park_discount_pct"],
    })

    entry_minutes = entry_at.hour * 60 + entry_at.minute
    for reservation in confirmed:
        start = _minutes(reservation["arrival_window_start"])
        end = _minutes(reservation["arrival_window_end"])
        if start <= entry_minutes < end:
            reservation["status"] = "REDEEMED"
            reservation["redeemed_visit_id"] = record["id"]
            record["reservation_id"] = reservation["id"]
            break

    score = domain.recompute_sharing_risk(season_pass, park_day)
    holder["sharing_risk_score"] = score
    domain.maybe_auto_open_case(season_pass, program, score)
    db.commit()
    return created_response(serializers.visit_out(record))


@bp.get("/visits")
def list_visits():
    require(*ALL_READ_ROLES)
    limit, offset = pagination()
    season_pass_id = query_string("season_pass_id")
    park_day_id = query_string("park_day_id")
    status = query_enum("status", VISIT_STATUSES)
    reservation_id = query_string("reservation_id")
    rows = db.rows("visits")
    if season_pass_id is not None:
        rows = [r for r in rows if r["season_pass_id"] == season_pass_id]
    if park_day_id is not None:
        rows = [r for r in rows if r["park_day_id"] == park_day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reservation_id is not None:
        rows = [r for r in rows if r["reservation_id"] == reservation_id]
    rows = sorted(rows, key=lambda r: (parse_instant(r["entry_at"]), r["created_at"]))
    return list_response([serializers.visit_out(r) for r in rows], limit, offset)


@bp.get("/visits/<visit_id>")
def get_visit(visit_id):
    require(*ALL_READ_ROLES)
    return object_response(serializers.visit_out(domain.get_visit(visit_id)))


@bp.post("/visits/<visit_id>/close")
def close_visit(visit_id):
    require(ROLE_GATE_AGENT)
    body = read_body({"spend_cents": field("integer", required=True, minimum=0)})
    visit = domain.get_visit(visit_id)
    if visit["status"] != "OPEN":
        raise ApiError("ERR_VISIT_ALREADY_CLOSED")
    visit["status"] = "CLOSED"
    visit["spend_cents"] = body["spend_cents"]
    db.commit()
    return object_response(serializers.visit_out(visit))
