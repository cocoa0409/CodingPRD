"""ProgramSession endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import db, new_record, touch
from clock import parse_iso, iso
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION,
    ERR_VENUE_TYPE_MISMATCH,
    ERR_INVALID_STATE,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_enum,
    require_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_venue, get_program
from services.serialize import program_view
from services.program_logic import (
    recompute_enrolled_count,
    recompute_waitlist_positions,
)

bp = Blueprint("programs", __name__)

PROGRAM_KINDS = {"CAMP", "CLASS"}


@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    body = get_body()
    require_string(body, "venue_id")
    venue_id = body["venue_id"]
    title = require_string(body, "title")
    program_kind = require_enum(body, "program_kind", PROGRAM_KINDS)
    min_age = require_int(body, "min_age")
    max_age = require_int(body, "max_age")
    if "starts_at" not in body or body["starts_at"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: starts_at")
    starts_at = parse_iso(body["starts_at"])
    if starts_at is None:
        raise err(ERR_INVALID_REQUEST, "starts_at is not a valid ISO8601 instant")
    capacity = require_int(body, "capacity")
    tuition = require_int(body, "tuition_cents")

    with db.lock:
        venue = get_venue(venue_id)
        # Venue-type compatibility (priority 11).
        if venue["venue_type"] != "CLASSROOM":
            raise err(ERR_VENUE_TYPE_MISMATCH, "Program requires a CLASSROOM venue")
        # Field-range (priority 20).
        if min_age < 0:
            raise err(ERR_VALIDATION, "min_age must be >= 0")
        if max_age < min_age:
            raise err(ERR_VALIDATION, "max_age must be >= min_age")
        if capacity < 1:
            raise err(ERR_VALIDATION, "capacity must be >= 1")
        if tuition < 0:
            raise err(ERR_VALIDATION, "tuition_cents must be >= 0")

        rec = new_record(with_version=True)
        rec.update({
            "venue_id": venue_id,
            "title": title,
            "program_kind": program_kind,
            "min_age": min_age,
            "max_age": max_age,
            "starts_at": iso(starts_at),
            "capacity": capacity,
            "tuition_cents": tuition,
            "enrolled_count": 0,
            "status": "ENROLLING",
            "_starts_at_dt": starts_at,
        })
        db.programs[rec["id"]] = rec
    return success(program_view(rec), status=201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator", "MembershipClerk"})
    limit, offset = parse_pagination()
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.programs.values())
        if venue_id is not None:
            records = [p for p in records if p["venue_id"] == venue_id]
        if status is not None:
            records = [p for p in records if p["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [program_view(p) for p in page]
    return success(data, status=200, pagination=meta)


@bp.route("/programs/<pid>", methods=["GET"])
def get_one_program(pid):
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    with db.lock:
        p = get_program(pid)
        return success(program_view(p), status=200)


@bp.route("/programs/<pid>/start", methods=["POST"])
def start_program(pid):
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    with db.lock:
        p = get_program(pid)
        # Permitted from ENROLLING or FULL once clock >= starts_at.
        if p["status"] not in ("ENROLLING", "FULL"):
            raise err(ERR_INVALID_STATE, "Program not in a startable state")
        if not (db.clock.now >= p["_starts_at_dt"]):
            raise err(ERR_INVALID_STATE, "Program start time has not arrived")
        # Purge waitlist: WAITLISTED -> CANCELLED.
        for r in db.registrations.values():
            if r["program_session_id"] == p["id"] and r["status"] == "WAITLISTED":
                r["status"] = "CANCELLED"
                r["waitlist_position"] = None
                touch(r)
        p["status"] = "STARTED"
        touch(p)
        return success(program_view(p), status=200)


@bp.route("/programs/<pid>/cancel", methods=["POST"])
def cancel_program(pid):
    _, role = authenticate()
    require_role(role, {"ProgramCoordinator"})
    with db.lock:
        p = get_program(pid)
        if p["status"] not in ("ENROLLING", "FULL"):
            raise err(ERR_INVALID_STATE, "Program not in a cancellable state")
        # Cascade: ENROLLED/WAITLISTED registrations -> CANCELLED.
        for r in db.registrations.values():
            if r["program_session_id"] == p["id"] and r["status"] in ("ENROLLED", "WAITLISTED"):
                r["status"] = "CANCELLED"
                r["waitlist_position"] = None
                touch(r)
        p["enrolled_count"] = 0
        p["status"] = "CANCELLED"
        touch(p)
        return success(program_view(p), status=200)
