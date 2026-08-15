"""Admin / configuration endpoints: schools, logical clock, purge, report."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_DUPLICATE_SCHOOL_CODE,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    optional_int,
    require_int,
    require_string,
    parse_iso8601,
    require_field,
)

bp = Blueprint("admin", __name__)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@bp.route("/schools", methods=["POST"])
@require_roles("DistrictAdministrator")
def create_school(_user_id: str, _role: str):
    body = get_json_body()
    name = require_string(body, "name")
    school_code = require_string(body, "school_code")
    enrollment_count = require_int(body, "enrollment_count", minimum=0)
    retention_days = optional_int(body, "retention_days", minimum=30)
    if retention_days is None:
        retention_days = 365

    # Uniqueness: school_code is case-sensitive and district-wide unique.
    for school in db.schools.values():
        if school["school_code"] == school_code:
            raise_err(ERR_DUPLICATE_SCHOOL_CODE, "school_code already in use")

    school = {
        "name": name,
        "school_code": school_code,
        "enrollment_count": enrollment_count,
        "retention_days": retention_days,
    }
    db.stamp_new(school)
    db.schools[school["id"]] = school
    return success_object(db.public(school), 201)


@bp.route("/schools/<school_id>", methods=["GET"])
@require_roles("IntakeCoordinator", "ThreatAssessor", "TeamLead", "DistrictAdministrator")
def get_school(school_id: str, _user_id: str, _role: str):
    school = db.schools.get(school_id)
    if school is None:
        raise_err(ERR_NOT_FOUND, "School id does not exist")
    return success_object(db.public(school))


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("DistrictAdministrator")
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    if new_dt < db.clock():
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be >= the current logical time")
    db.set_clock(new_dt)
    domain.apply_clock_transitions(new_dt)
    return success_object({"current_utc": db.clock_iso()})


# ---------------------------------------------------------------------------
# Records retention purge
# ---------------------------------------------------------------------------

@bp.route("/records-retention/purge", methods=["POST"])
@require_roles("DistrictAdministrator")
def records_retention_purge(_user_id: str, _role: str):
    purged_count, purged_ids = domain.run_retention_purge()
    return success_object({"purged_count": purged_count, "purged_case_ids": purged_ids})


# ---------------------------------------------------------------------------
# District annual report
# ---------------------------------------------------------------------------

@bp.route("/annual-reports/district", methods=["GET"])
@require_roles("TeamLead", "DistrictAdministrator")
def district_annual_report(_user_id: str, _role: str):
    school_year = request.args.get("school_year")
    if school_year is None or school_year == "":
        raise_err(ERR_INVALID_REQUEST, "school_year query parameter is required")
    report = domain.build_district_annual_report(school_year)
    return success_object(report)
