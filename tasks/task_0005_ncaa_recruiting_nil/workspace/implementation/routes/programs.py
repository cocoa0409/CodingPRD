"""Programs and recruiting calendar Periods."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_INVALID_INTERVAL,
    ERR_PERIOD_OVERLAP,
    invalid_request,
    not_found,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("programs", __name__)


SPORT_CODES = {"FOOTBALL", "MBB", "WBB", "BASEBALL", "SOFTBALL"}
PERIOD_TYPES = {"CONTACT", "QUIET", "DEAD"}


# ---------- Programs --------------------------------------------------------
@bp.post("/ncaa/programs")
def create_program():
    require_roles("ComplianceOfficer")
    body = get_body()
    sport_code = require_field(body, "sport_code", str)
    require_enum(sport_code, "sport_code", SPORT_CODES)
    school_name = require_field(body, "school_name", str)
    if not school_name:
        raise invalid_request("school_name must be non-empty.")
    cap = require_field(body, "scholarship_slot_cap", int)
    if not (1 <= cap <= 130):
        raise invalid_request("scholarship_slot_cap must be in [1, 130].")
    row = {
        "id": db.new_id(),
        "sport_code": sport_code,
        "school_name": school_name,
        "scholarship_slot_cap": cap,
        "slots_committed": 0,
        "slots_projected": 0,
        "penalty_tier": "NONE",
    }
    db.stamp_create(row)
    db.programs[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/programs/<program_id>")
def get_program(program_id):
    require_roles("ComplianceOfficer", "Coach", "NILReviewer",
                  "EligibilityCenter", "StudentAthlete")
    row = db.programs.get(program_id)
    if row is None:
        raise not_found("Program not found.")
    return ok_object(row)


@bp.get("/ncaa/programs")
def list_programs():
    require_roles("ComplianceOfficer", "Coach", "NILReviewer",
                  "EligibilityCenter", "StudentAthlete")
    limit, offset = parse_pagination()
    sport = request.args.get("sport_code")
    rows = list(db.programs.values())
    if sport is not None:
        if sport not in SPORT_CODES:
            raise invalid_request("sport_code filter is not a valid enum.")
        rows = [r for r in rows if r["sport_code"] == sport]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.get("/ncaa/programs/<program_id>/utilization")
def get_program_utilization(program_id):
    require_roles("ComplianceOfficer", "Coach")
    program = db.programs.get(program_id)
    if program is None:
        raise not_found("Program not found.")
    variant = request.args.get("variant", "base")
    if variant not in ("base", "projected"):
        raise invalid_request("variant must be 'base' or 'projected'.")
    if variant == "base":
        slot_count = services.compute_slots_committed(program_id)
    else:
        slot_count = services.compute_slots_projected(program_id)
    return ok_object({
        "program_id": program_id,
        "variant": variant,
        "slot_count": slot_count,
        "scholarship_slot_cap": program["scholarship_slot_cap"],
    })


# ---------- Periods ---------------------------------------------------------
@bp.post("/ncaa/programs/<program_id>/periods")
def create_period(program_id):
    require_roles("ComplianceOfficer")
    if program_id not in db.programs:
        raise not_found("Program not found.")
    body = get_body()
    period_type = require_field(body, "period_type", str)
    require_enum(period_type, "period_type", PERIOD_TYPES)
    starts_at = require_field(body, "starts_at", str)
    ends_at = require_field(body, "ends_at", str)
    # Parse and validate the interval shape
    try:
        s_dt = db.parse_iso(starts_at)
        e_dt = db.parse_iso(ends_at)
    except ValueError as exc:
        raise invalid_request(str(exc))
    if not (s_dt < e_dt):
        raise APIError(
            ERR_INVALID_INTERVAL,
            "Period starts_at must be strictly earlier than ends_at.",
            422,
        )
    # Overlap check: half-open [starts_at, ends_at) intersect any existing
    # period for the same program. Adjacency permitted.
    for existing in db.periods.values():
        if existing["program_id"] != program_id:
            continue
        ex_s = db.parse_iso(existing["starts_at"])
        ex_e = db.parse_iso(existing["ends_at"])
        # Two half-open intervals [a, b) and [c, d) overlap iff a < d and c < b.
        if s_dt < ex_e and ex_s < e_dt:
            raise APIError(
                ERR_PERIOD_OVERLAP,
                "Period overlaps an existing Period for this program.",
                422,
            )
    row = {
        "id": db.new_id(),
        "program_id": program_id,
        "period_type": period_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    db.stamp_create(row)
    db.periods[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/programs/<program_id>/periods")
def list_periods(program_id):
    require_roles("ComplianceOfficer", "Coach")
    if program_id not in db.programs:
        raise not_found("Program not found.")
    limit, offset = parse_pagination()
    period_type = request.args.get("period_type")
    if period_type is not None and period_type not in PERIOD_TYPES:
        raise invalid_request("period_type filter is not a valid enum.")
    rows = [p for p in db.periods.values() if p["program_id"] == program_id]
    if period_type is not None:
        rows = [p for p in rows if p["period_type"] == period_type]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.get("/ncaa/periods/<period_id>")
def get_period(period_id):
    require_roles("ComplianceOfficer", "Coach")
    row = db.periods.get(period_id)
    if row is None:
        raise not_found("Period not found.")
    return ok_object(row)
