"""School and yield-report routes."""

from flask import Blueprint

import db
import errors
import response as resp
import util
from middleware import require_auth
from routes._helpers import (
    get_json_body,
    optional_field,
    parse_pagination,
    paginate,
    require_field,
)
from services import calculations
from services.serializers import serialize_school


bp = Blueprint("schools", __name__)


# --------------------------------------------------------------------------- #
# POST /schools (PlatformAdmin)
# --------------------------------------------------------------------------- #

@bp.route("/schools", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_school():
    body = get_json_body()
    name = require_field(body, "name", kind="string")
    target_class_size = require_field(body, "target_class_size", kind="integer")
    ed_str = require_field(body, "ed_deadline_iso", kind="string")
    ea_str = require_field(body, "ea_deadline_iso", kind="string")
    rd_str = require_field(body, "rd_deadline_iso", kind="string")
    rolling_open = optional_field(body, "rolling_open", kind="boolean", default=False)
    requires_css = optional_field(body, "requires_css_profile", kind="boolean", default=False)
    cooldown_ms = optional_field(body, "cooldown_ms", kind="integer", default=86_400_000)

    if not name.strip():
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'name' must not be empty.")
    if target_class_size < 1:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'target_class_size' must be >= 1.")
    if cooldown_ms is None or cooldown_ms < 0:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Field 'cooldown_ms' must be >= 0.")

    ed_dt = util.parse_iso(ed_str)
    ea_dt = util.parse_iso(ea_str)
    rd_dt = util.parse_iso(rd_str)
    if ed_dt is None or ea_dt is None or rd_dt is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Deadline fields must be valid ISO 8601 timestamps.")

    # Uniqueness check on school name
    for existing in db.schools.values():
        if existing["name"] == name:
            errors.raise_error(errors.ERR_DUPLICATE_RESOURCE,
                               "A school with this name already exists.")

    # Priority 21: deadline ordering — strict
    if not (ed_dt < ea_dt < rd_dt):
        errors.raise_error(errors.ERR_SCHOOL_DEADLINE_ORDER,
                           "Deadlines must satisfy strict ed < ea < rd ordering.")

    row = {
        "name": name,
        "target_class_size": target_class_size,
        "ed_deadline_iso": ed_dt,
        "ea_deadline_iso": ea_dt,
        "rd_deadline_iso": rd_dt,
        "rolling_open": bool(rolling_open),
        "requires_css_profile": bool(requires_css),
        "confirmed_enrollment_count": 0,
        "posture": "OPEN",
    }
    util.stamp_create(row)
    db.schools[row["id"]] = row

    # Create companion AdmissionCycle. Per PRD §3.3 the cycle is the 1:1
    # companion of the school; the cycle row carries its own server-minted
    # UUID identifier (§2.4), and PRD offers no separate discovery path for
    # the cycle id, so we mint the cycle's id to equal the school's id —
    # consistent with the "companion" framing and accessible to clients that
    # only hold the school id.
    cycle = {
        "id": row["id"],
        "school_id": row["id"],
        "clock_iso": row["created_at"],
        "last_yield_run_at": None,
        "yield_run_count": 0,
        "cooldown_ms": int(cooldown_ms),
    }
    util.stamp_create(cycle)
    db.admission_cycles[cycle["id"]] = cycle

    return resp.success_object(serialize_school(row), http_status=201)


# --------------------------------------------------------------------------- #
# GET /schools/{id}
# --------------------------------------------------------------------------- #

@bp.route("/schools/<school_id>", methods=["GET"])
@require_auth(["Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"])
def get_school(school_id):
    row = db.schools.get(school_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "School not found.")
    return resp.success_object(serialize_school(row))


# --------------------------------------------------------------------------- #
# GET /schools
# --------------------------------------------------------------------------- #

@bp.route("/schools", methods=["GET"])
@require_auth(["Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin"])
def list_schools():
    limit, offset = parse_pagination()
    rows = sorted(db.schools.values(), key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return resp.success_array(
        [serialize_school(r) for r in page],
        limit=limit, offset=offset, total_count=total,
    )


# --------------------------------------------------------------------------- #
# GET /schools/{id}/yield-report
# --------------------------------------------------------------------------- #

@bp.route("/schools/<school_id>/yield-report", methods=["GET"])
@require_auth(["AdmissionsOfficer", "PlatformAdmin"])
def yield_report(school_id):
    row = db.schools.get(school_id)
    if row is None:
        errors.raise_error(errors.ERR_RESOURCE_NOT_FOUND, "School not found.")

    yield_rate, admitted_count, enrolled_count = calculations.compute_yield_rate(school_id)
    waitlist_depth = sum(
        1 for a in db.applications.values()
        if a["school_id"] == school_id and a["status"] == "WAITLISTED"
    )

    payload = {
        "school_id": school_id,
        "yield_rate": yield_rate,
        "confirmed_enrollment_count": row["confirmed_enrollment_count"],
        "admitted_count": admitted_count,
        "enrolled_count": enrolled_count,
        "waitlist_depth": waitlist_depth,
    }
    return resp.success_object(payload)
