"""Program and Enrollment routes (PRD 3.8)."""
from flask import Blueprint, request

from clock import parse_iso
from db import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN_ROLE,
    ERR_FACILITY_POSTURE_BLOCK,
    ERR_PROGRAM_FULL,
    ERR_STALE_PROGRAM_VERSION,
)
from helpers import (
    get_json_body,
    require_fields,
    require_enum,
    lookup,
    base_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import program_out, enrollment_out
from services import pricing
from services.derive import recompute_program, touch

bp = Blueprint("programs", __name__)

READ_ROLES = ["FacilityManager", "FrontDesk", "Member", "Instructor"]


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------
@bp.post("/v1/programs")
def create_program():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "lane_id", "kind", "capacity", "price_cents",
                          "session_start_utc", "session_end_utc"])
    facility = lookup(db.facilities, body["facility_id"])
    lane = lookup(db.lanes, body["lane_id"])
    if lane["facility_id"] != facility["id"]:
        raise err(ERR_NOT_FOUND, "Lane not in facility scope")
    require_enum(body["kind"], {"LEAGUE", "CLINIC"}, "kind")

    capacity = body["capacity"]
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise err(ERR_INVALID_REQUEST, "capacity must be >= 1")
    price_cents = body["price_cents"]
    if not isinstance(price_cents, int) or isinstance(price_cents, bool) or price_cents < 0:
        raise err(ERR_INVALID_REQUEST, "price_cents must be >= 0")

    try:
        start = parse_iso(body["session_start_utc"])
        end = parse_iso(body["session_end_utc"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime")
    if end <= start:
        raise err(ERR_INVALID_REQUEST, "session_end_utc must be after session_start_utc")

    program = base_common_fields()
    program.update({
        "facility_id": body["facility_id"],
        "lane_id": body["lane_id"],
        "kind": body["kind"],
        "capacity": capacity,
        "price_cents": price_cents,
        "session_start_utc": body["session_start_utc"],
        "session_end_utc": body["session_end_utc"],
        "enrolled_count": 0,
        "status": "OPEN",
    })
    db.programs[program["id"]] = program
    return success(program_out(program), status=201)


@bp.get("/v1/programs/<program_id>")
def get_program(program_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    program = lookup(db.programs, program_id)
    return success(program_out(program), status=200)


@bp.get("/v1/programs")
def list_programs():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    lane_id = request.args.get("lane_id")
    items = [
        p for p in db.programs.values()
        if (facility_id is None or p["facility_id"] == facility_id)
        and (lane_id is None or p["lane_id"] == lane_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([program_out(p) for p in page], status=200, pagination=meta)


@bp.post("/v1/programs/<program_id>/close")
def close_program(program_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    program = lookup(db.programs, program_id)
    if program["status"] == "CLOSED":
        raise err(ERR_INVALID_STATE, "Program is already CLOSED")
    program["status"] = "CLOSED"
    touch(program)
    return success(program_out(program), status=200)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------
@bp.post("/v1/programs/<program_id>/enrollments")
def enroll(program_id):
    user_id, role = authenticate()
    require_role(role, ["Member", "FrontDesk"])
    program = lookup(db.programs, program_id)
    body = get_json_body()
    require_fields(body, ["member_id", "expected_program_version"])
    member = lookup(db.members, body["member_id"])
    facility = db.facilities[program["facility_id"]]

    if role == "Member" and user_id != body["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only enroll themselves")

    expected_version = body["expected_program_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_program_version must be an integer")

    # Priority 7: facility posture (CLOSED blocks all enrollment).
    if facility["posture"] == "CLOSED":
        raise err(ERR_FACILITY_POSTURE_BLOCK, "Facility is CLOSED")

    # Priority 14: program capacity / closed / duplicate.
    if program["status"] == "CLOSED":
        raise err(ERR_PROGRAM_FULL, "Program is CLOSED")
    if program["enrolled_count"] >= program["capacity"]:
        raise err(ERR_PROGRAM_FULL, "Program is at capacity")
    already = any(
        e["program_id"] == program_id and e["member_id"] == body["member_id"]
        and e["status"] == "ENROLLED"
        for e in db.enrollments.values()
    )
    if already:
        raise err(ERR_PROGRAM_FULL, "Member already enrolled")

    # Priority 15: OCC stale program version.
    if expected_version != program["version"]:
        raise err(ERR_STALE_PROGRAM_VERSION, "Program version is stale")

    enrollment = base_common_fields()
    enrollment.update({
        "facility_id": program["facility_id"],
        "program_id": program_id,
        "member_id": body["member_id"],
        "status": "ENROLLED",
        "charged_cents": program["price_cents"],
    })
    db.enrollments[enrollment["id"]] = enrollment

    # Update program: enrolled_count += 1, OPEN->FULL if capacity reached, bump version.
    program["enrolled_count"] += 1
    if program["status"] != "CLOSED" and program["enrolled_count"] == program["capacity"]:
        program["status"] = "FULL"
    touch(program)

    return success(enrollment_out(enrollment), status=201)


@bp.get("/v1/programs/<program_id>/enrollments")
def list_program_enrollments(program_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    lookup(db.programs, program_id)
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    items = [
        e for e in db.enrollments.values()
        if e["program_id"] == program_id
        and (member_id is None or e["member_id"] == member_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([enrollment_out(e) for e in page], status=200, pagination=meta)


@bp.get("/v1/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    enrollment = lookup(db.enrollments, enrollment_id)
    return success(enrollment_out(enrollment), status=200)


@bp.get("/v1/enrollments")
def list_enrollments():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    program_id = request.args.get("program_id")
    member_id = request.args.get("member_id")
    items = [
        e for e in db.enrollments.values()
        if (facility_id is None or e["facility_id"] == facility_id)
        and (program_id is None or e["program_id"] == program_id)
        and (member_id is None or e["member_id"] == member_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([enrollment_out(e) for e in page], status=200, pagination=meta)


@bp.post("/v1/enrollments/<enrollment_id>/withdraw")
def withdraw(enrollment_id):
    user_id, role = authenticate()
    require_role(role, ["Member", "FacilityManager"])
    enrollment = lookup(db.enrollments, enrollment_id)
    if role == "Member" and user_id != enrollment["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only withdraw their own enrollment")
    if enrollment["status"] != "ENROLLED":
        raise err(ERR_INVALID_STATE, "Enrollment is not ENROLLED")

    enrollment["status"] = "WITHDRAWN"
    touch(enrollment)

    program = db.programs.get(enrollment["program_id"])
    if program is not None:
        program["enrolled_count"] -= 1
        if program["enrolled_count"] < 0:
            program["enrolled_count"] = 0
        if program["status"] == "FULL":
            program["status"] = "OPEN"
        touch(program)

    # Refund: floor(charged_cents / token_price_cents) tokens to member wallet.
    member = db.members.get(enrollment["member_id"])
    if member is not None:
        facility = db.facilities.get(enrollment["facility_id"])
        token_price = facility["token_price_cents"] if facility else 1
        refund_tokens = pricing.cents_to_tokens_floor(enrollment["charged_cents"], token_price)
        member["token_balance"] += refund_tokens
        touch(member)

    return success(enrollment_out(enrollment), status=200)
