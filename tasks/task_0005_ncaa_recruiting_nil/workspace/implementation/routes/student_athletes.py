"""StudentAthlete intake and read."""

from flask import Blueprint, request

import db
from errors import invalid_request, not_found
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

bp = Blueprint("student_athletes", __name__)


SPORT_CODES = {"FOOTBALL", "MBB", "WBB", "BASEBALL", "SOFTBALL"}
ELIGIBILITY_STATUSES = {"UNCERTIFIED", "CERTIFIED", "INELIGIBLE"}


@bp.post("/ncaa/student-athletes")
def create_athlete():
    require_roles("ComplianceOfficer")
    body = get_body()
    full_name = require_field(body, "full_name", str)
    if not full_name:
        raise invalid_request("full_name must be non-empty.")
    sport_code = require_field(body, "sport_code", str)
    require_enum(sport_code, "sport_code", SPORT_CODES)
    # gpa may arrive as float or int from the JSON parser
    raw_gpa = body.get("gpa")
    if raw_gpa is None:
        raise invalid_request("Required field 'gpa' is missing.")
    if isinstance(raw_gpa, bool) or not isinstance(raw_gpa, (int, float)):
        raise invalid_request("gpa must be a number.")
    gpa = float(raw_gpa)
    if not (0.0 <= gpa <= 4.0):
        raise invalid_request("gpa must be in [0.000, 4.000].")
    amateurism_flag = optional_field(body, "amateurism_flag", bool, default=True)
    row = {
        "id": db.new_id(),
        "full_name": full_name,
        "sport_code": sport_code,
        "gpa": gpa,
        "amateurism_flag": bool(amateurism_flag),
        "enrolled_program_id": None,
        "eligibility_status": "UNCERTIFIED",
        "in_transfer_portal": False,
    }
    db.stamp_create(row)
    db.student_athletes[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/student-athletes/<athlete_id>")
def get_athlete(athlete_id):
    require_roles("ComplianceOfficer", "Coach", "NILReviewer",
                  "EligibilityCenter", "StudentAthlete")
    row = db.student_athletes.get(athlete_id)
    if row is None:
        raise not_found("StudentAthlete not found.")
    return ok_object(row)


@bp.get("/ncaa/student-athletes")
def list_athletes():
    require_roles("ComplianceOfficer", "Coach", "NILReviewer",
                  "EligibilityCenter")
    limit, offset = parse_pagination()
    sport = request.args.get("sport_code")
    elig = request.args.get("eligibility_status")
    in_portal = request.args.get("in_transfer_portal")
    enrolled = request.args.get("enrolled_program_id")
    if sport is not None and sport not in SPORT_CODES:
        raise invalid_request("sport_code filter is not a valid enum.")
    if elig is not None and elig not in ELIGIBILITY_STATUSES:
        raise invalid_request("eligibility_status filter is not a valid enum.")
    if in_portal is not None:
        if in_portal.lower() in ("true", "1"):
            in_portal_bool = True
        elif in_portal.lower() in ("false", "0"):
            in_portal_bool = False
        else:
            raise invalid_request("in_transfer_portal must be 'true' or 'false'.")
    else:
        in_portal_bool = None
    rows = list(db.student_athletes.values())
    if sport is not None:
        rows = [r for r in rows if r["sport_code"] == sport]
    if elig is not None:
        rows = [r for r in rows if r["eligibility_status"] == elig]
    if in_portal_bool is not None:
        rows = [r for r in rows if r["in_transfer_portal"] == in_portal_bool]
    if enrolled is not None:
        rows = [r for r in rows if r["enrolled_program_id"] == enrolled]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)
