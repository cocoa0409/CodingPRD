"""Pass tiers, park days, blockout assignments and passholders."""

from flask import Blueprint

import serializers
from db import db
from errors import ApiError
from middleware import (ROLE_COMPLIANCE_OFFICER, ROLE_GATE_AGENT, ROLE_PASS_OFFICE_CLERK,
                        ROLE_PROGRAM_ADMIN, require)
from response import created_response, list_response, object_response
from services import calc, domain
from validate import field, pagination, query_enum, query_string, read_body

bp = Blueprint("catalog", __name__)

TIER_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")
PARKING_BENEFITS = ("NONE", "DISCOUNT", "INCLUDED")
DAY_CLASSES = ("STANDARD", "PEAK", "CAPACITY_LOCKED")
ASSIGNMENT_STATUSES = ("ACTIVE", "LIFTED")
ASSIGNMENT_SOURCES = ("MANUAL", "CAPACITY_ADJUSTED")
HOLDER_STATUSES = ("ACTIVE", "BANNED")

PARK_DAY_PROGRAM_STATUSES = ("DESIGN", "SALES_OPEN", "SEASON_ACTIVE", "RENEWAL_OPEN")


# --------------------------------------------------------------- pass tiers
TIER_SPEC = {
    "program_id": field("string", required=True),
    "name": field("string", required=True),
    "tier_rank": field("integer", required=True, minimum=1, maximum=9),
    "base_price_cents": field("integer", required=True, minimum=1000),
    "parking_benefit": field("enum", required=True, enum=PARKING_BENEFITS),
    "in_park_discount_pct": field("number", required=True, minimum=0, maximum=0.30, max_decimals=2),
    "reservation_required_on_peak": field("boolean", required=True),
    "peak_reservation_quota": field("integer", required=True, minimum=1, maximum=20),
}


@bp.post("/pass-tiers")
def create_tier():
    require(ROLE_PROGRAM_ADMIN)
    body = read_body(TIER_SPEC)
    program = domain.get_program(body["program_id"])
    if program["status"] not in ("DESIGN", "SALES_OPEN"):
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    for tier in domain.program_tiers(program["id"]):
        if tier["name"] == body["name"]:
            raise ApiError("ERR_INVALID_REQUEST", "tier name must be unique within the program")
        if tier["tier_rank"] == body["tier_rank"]:
            raise ApiError("ERR_INVALID_REQUEST", "tier_rank must be unique within the program")
    record = db.insert("pass_tiers", {
        "program_id": program["id"],
        "name": body["name"],
        "tier_rank": body["tier_rank"],
        "base_price_cents": body["base_price_cents"],
        "parking_benefit": body["parking_benefit"],
        "in_park_discount_pct": body["in_park_discount_pct"],
        "reservation_required_on_peak": body["reservation_required_on_peak"],
        "peak_reservation_quota": body["peak_reservation_quota"],
        "status": "DRAFT",
    })
    db.commit()
    return created_response(serializers.tier_out(record))


@bp.get("/pass-tiers")
def list_tiers():
    require()
    limit, offset = pagination()
    program_id = query_string("program_id")
    status = query_enum("status", TIER_STATUSES)
    rows = db.rows("pass_tiers")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["tier_rank"], r["created_at"]))
    return list_response([serializers.tier_out(r) for r in rows], limit, offset)


@bp.get("/pass-tiers/<tier_id>")
def get_tier(tier_id):
    require()
    return object_response(serializers.tier_out(domain.get_tier(tier_id)))


@bp.post("/pass-tiers/<tier_id>/status")
def set_tier_status(tier_id):
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({"target_status": field("enum", required=True, enum=TIER_STATUSES)})
    tier = domain.get_tier(tier_id)
    target = body["target_status"]
    current = tier["status"]
    if current == "DRAFT" and target == "PUBLISHED":
        program = domain.get_program(tier["program_id"])
        if program["status"] not in ("DESIGN", "SALES_OPEN"):
            raise ApiError(
                "ERR_TIER_NOT_PUBLISHED",
                "the program has moved past SALES_OPEN",
            )
    elif current == "PUBLISHED" and target == "RETIRED":
        for season_pass in domain.program_passes(tier["program_id"]):
            if (
                season_pass["tier_id"] == tier["id"]
                and season_pass["pass_status"] in domain.LIVE_PASS_STATUSES
            ):
                raise ApiError(
                    "ERR_TIER_NOT_PUBLISHED",
                    "the tier still carries live passes",
                )
    else:
        raise ApiError("ERR_TIER_NOT_PUBLISHED")
    tier["status"] = target
    db.force_touch(tier)
    db.commit()
    return object_response(serializers.tier_out(tier))


# ---------------------------------------------------------------- park days
PARK_DAY_SPEC = {
    "program_id": field("string", required=True),
    "calendar_date": field("date", required=True),
    "capacity_total": field("integer", required=True, minimum=1),
    "forecast_attendance": field("integer", required=True, minimum=0),
}


@bp.post("/park-days")
def create_park_day():
    require(ROLE_PROGRAM_ADMIN)
    body = read_body(PARK_DAY_SPEC)
    program = domain.get_program(body["program_id"])
    if program["status"] not in PARK_DAY_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    for day in domain.program_park_days(program["id"]):
        if day["calendar_date"] == body["calendar_date"]:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "calendar_date must be unique within the program",
            )
    utilization, day_class, slot_capacity, window_capacity = calc.derive_posture(
        program, body["capacity_total"], body["forecast_attendance"]
    )
    record = db.insert("park_days", {
        "program_id": program["id"],
        "calendar_date": body["calendar_date"],
        "capacity_total": body["capacity_total"],
        "forecast_attendance": body["forecast_attendance"],
        "forecast_utilization_pct": utilization,
        "day_class": day_class,
        "reservation_slot_capacity": slot_capacity,
        "window_slot_capacity": window_capacity,
        "grant_count": 0,
    })
    if day_class == "CAPACITY_LOCKED":
        domain.install_capacity_blockouts(record)
    db.commit()
    return created_response(serializers.park_day_out(record))


@bp.get("/park-days")
def list_park_days():
    require()
    limit, offset = pagination()
    program_id = query_string("program_id")
    day_class = query_enum("day_class", DAY_CLASSES)
    rows = db.rows("park_days")
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if day_class is not None:
        rows = [r for r in rows if r["day_class"] == day_class]
    rows = sorted(rows, key=lambda r: (r["calendar_date"], r["created_at"]))
    return list_response([serializers.park_day_out(r) for r in rows], limit, offset)


@bp.get("/park-days/<park_day_id>")
def get_park_day(park_day_id):
    require()
    return object_response(serializers.park_day_out(domain.get_park_day(park_day_id)))


@bp.post("/park-days/<park_day_id>/forecast")
def reforecast(park_day_id):
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({
        "forecast_attendance": field("integer", required=True, minimum=0),
        "capacity_total": field("integer", minimum=1),
    })
    park_day = domain.get_park_day(park_day_id)
    program = domain.get_program(park_day["program_id"])
    if program["status"] not in PARK_DAY_PROGRAM_STATUSES:
        raise ApiError("ERR_PROGRAM_STATUS_INVALID")
    park_day["forecast_attendance"] = body["forecast_attendance"]
    if "capacity_total" in body:
        park_day["capacity_total"] = body["capacity_total"]
    domain.apply_posture(park_day, program)
    db.force_touch(park_day)
    db.commit()
    return object_response(serializers.park_day_out(park_day))


# ------------------------------------------------------- blockout assignments
@bp.post("/blockout-assignments")
def create_assignment():
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({
        "tier_id": field("string", required=True),
        "park_day_id": field("string", required=True),
        "expected_park_day_version": field("integer", required=True),
    })
    tier = domain.get_tier(body["tier_id"])
    park_day = domain.get_park_day(body["park_day_id"])
    if body["expected_park_day_version"] != park_day["version"]:
        raise ApiError("ERR_STALE_PARK_DAY_VERSION")
    if tier["program_id"] != park_day["program_id"]:
        raise ApiError("ERR_PARK_DAY_PROGRAM_MISMATCH")
    if domain.has_active_blockout(tier["id"], park_day["id"]):
        raise ApiError("ERR_DUPLICATE_BLOCKOUT_ASSIGNMENT")
    record = db.insert("blockout_assignments", {
        "tier_id": tier["id"],
        "park_day_id": park_day["id"],
        "source": "MANUAL",
        "status": "ACTIVE",
        "lift_reason": None,
    })
    domain.cancel_blocked_reservations_for_tier(tier["id"], park_day["id"])
    db.force_touch(park_day)
    db.commit()
    return created_response(serializers.assignment_out(record))


@bp.get("/blockout-assignments")
def list_assignments():
    require()
    limit, offset = pagination()
    tier_id = query_string("tier_id")
    park_day_id = query_string("park_day_id")
    status = query_enum("status", ASSIGNMENT_STATUSES)
    source = query_enum("source", ASSIGNMENT_SOURCES)
    rows = db.rows("blockout_assignments")
    if tier_id is not None:
        rows = [r for r in rows if r["tier_id"] == tier_id]
    if park_day_id is not None:
        rows = [r for r in rows if r["park_day_id"] == park_day_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.assignment_out(r) for r in rows], limit, offset)


@bp.get("/blockout-assignments/<assignment_id>")
def get_assignment(assignment_id):
    require()
    return object_response(serializers.assignment_out(domain.get_assignment(assignment_id)))


@bp.post("/blockout-assignments/<assignment_id>/lift")
def lift_assignment(assignment_id):
    require(ROLE_PROGRAM_ADMIN)
    body = read_body({"reason": field("string", required=True)})
    assignment = domain.get_assignment(assignment_id)
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_ALREADY_LIFTED")
    park_day = domain.get_park_day(assignment["park_day_id"])
    if park_day["day_class"] == "CAPACITY_LOCKED":
        raise ApiError("ERR_PARK_DAY_CAPACITY_LOCKED")
    assignment["status"] = "LIFTED"
    assignment["lift_reason"] = body["reason"]
    db.force_touch(assignment)
    db.commit()
    return object_response(serializers.assignment_out(assignment))


# -------------------------------------------------------------- passholders
@bp.post("/passholders")
def create_passholder():
    require(ROLE_PASS_OFFICE_CLERK)
    body = read_body({
        "full_name": field("string", required=True),
        "email": field("string", required=True),
        "date_of_birth": field("date", required=True),
    })
    for holder in db.rows("passholders"):
        if holder["email"] == body["email"]:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique")
    record = db.insert("passholders", {
        "full_name": body["full_name"],
        "email": body["email"],
        "date_of_birth": body["date_of_birth"],
        "sharing_risk_score": 0,
        "status": "ACTIVE",
    })
    db.commit()
    return created_response(serializers.passholder_out(record))


@bp.get("/passholders")
def list_passholders():
    require(ROLE_PROGRAM_ADMIN, ROLE_PASS_OFFICE_CLERK, ROLE_GATE_AGENT, ROLE_COMPLIANCE_OFFICER)
    limit, offset = pagination()
    email = query_string("email")
    status = query_enum("status", HOLDER_STATUSES)
    rows = db.rows("passholders")
    if email is not None:
        rows = [r for r in rows if r["email"] == email]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return list_response([serializers.passholder_out(r) for r in rows], limit, offset)


@bp.get("/passholders/<passholder_id>")
def get_passholder(passholder_id):
    require()
    return object_response(serializers.passholder_out(domain.get_passholder(passholder_id)))
