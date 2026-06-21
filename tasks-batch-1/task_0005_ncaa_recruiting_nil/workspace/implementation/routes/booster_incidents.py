"""BoosterIncident endpoints."""

from flask import Blueprint, g, request

import db
import services
from errors import (
    APIError,
    ERR_STALE_INCIDENT_VERSION,
    ERR_ZERO_VALUE_INCIDENT,
    invalid_request,
    invalid_state,
    not_found,
)
from helpers import (
    get_body,
    paginate,
    parse_pagination,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object

bp = Blueprint("booster_incidents", __name__)


INCIDENT_STATUSES = {"REPORTED", "INVESTIGATING", "SUSTAINED", "DISMISSED"}


@bp.post("/ncaa/booster-incidents")
def create_incident():
    require_roles("ComplianceOfficer")
    body = get_body()
    program_id = require_field(body, "program_id", str)
    booster_name = require_field(body, "booster_name", str)
    athlete_id = require_field(body, "student_athlete_id", str)
    raw_value = body.get("alleged_value_cents")
    if raw_value is None:
        raise invalid_request("Required field 'alleged_value_cents' is missing.")
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise invalid_request("alleged_value_cents must be an integer.")
    if raw_value < 0:
        raise invalid_request("alleged_value_cents must be >= 0.")
    # FK resolution
    program = db.programs.get(program_id)
    if program is None:
        raise not_found("Program not found.")
    athlete = db.student_athletes.get(athlete_id)
    if athlete is None:
        raise not_found("StudentAthlete not found.")
    # Zero-value boundary (priority 18)
    if int(raw_value) == 0:
        raise APIError(
            ERR_ZERO_VALUE_INCIDENT,
            "BoosterIncident.alleged_value_cents must be strictly greater than 0.",
            422,
        )
    row = {
        "id": db.new_id(),
        "program_id": program_id,
        "booster_name": booster_name,
        "student_athlete_id": athlete_id,
        "alleged_value_cents": int(raw_value),
        "severity_weight": 0,
        "status": "REPORTED",
    }
    db.stamp_create(row)
    db.booster_incidents[row["id"]] = row
    return ok_object(row, 201)


@bp.get("/ncaa/booster-incidents/<incident_id>")
def get_incident(incident_id):
    require_roles("ComplianceOfficer")
    row = db.booster_incidents.get(incident_id)
    if row is None:
        raise not_found("BoosterIncident not found.")
    return ok_object(row)


@bp.get("/ncaa/booster-incidents")
def list_incidents():
    require_roles("ComplianceOfficer")
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    athlete_id = request.args.get("student_athlete_id")
    status = request.args.get("status")
    if status is not None and status not in INCIDENT_STATUSES:
        raise invalid_request("status filter is not a valid enum.")
    rows = list(db.booster_incidents.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if athlete_id is not None:
        rows = [r for r in rows if r["student_athlete_id"] == athlete_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array(page, limit=limit, offset=offset,
                    total_count=total, has_more=has_more)


@bp.post("/ncaa/booster-incidents/<incident_id>/open-investigation")
def open_investigation(incident_id):
    require_roles("ComplianceOfficer")
    inc = db.booster_incidents.get(incident_id)
    if inc is None:
        raise not_found("BoosterIncident not found.")
    if inc["status"] != "REPORTED":
        raise invalid_state("BoosterIncident is not in REPORTED state.")
    inc["status"] = "INVESTIGATING"
    db.stamp_update(inc)
    return ok_object(inc)


@bp.post("/ncaa/booster-incidents/<incident_id>/sustain")
def sustain_incident(incident_id):
    require_roles("ComplianceOfficer")
    inc = db.booster_incidents.get(incident_id)
    if inc is None:
        raise not_found("BoosterIncident not found.")
    body = get_body()
    if "expected_boosterincident_version" not in body:
        raise invalid_request("expected_boosterincident_version is required.")
    raw_v = body["expected_boosterincident_version"]
    if isinstance(raw_v, bool) or not isinstance(raw_v, int):
        raise invalid_request("expected_boosterincident_version must be an integer.")
    if inc["status"] != "INVESTIGATING":
        raise invalid_state("BoosterIncident is not in INVESTIGATING state.")
    if int(raw_v) != int(inc["version"]):
        raise APIError(
            ERR_STALE_INCIDENT_VERSION,
            "expected_boosterincident_version does not match.",
            412,
        )
    inc["status"] = "SUSTAINED"
    inc["severity_weight"] = services.severity_weight_for(
        inc["alleged_value_cents"]
    )
    db.stamp_update(inc)
    # Recompute program penalty; on POSTSEASON_BAN, cascade-WITHDRAW SENT offers.
    services.recompute_and_apply_penalty(inc["program_id"])
    return ok_object(inc)


@bp.post("/ncaa/booster-incidents/<incident_id>/dismiss")
def dismiss_incident(incident_id):
    require_roles("ComplianceOfficer")
    inc = db.booster_incidents.get(incident_id)
    if inc is None:
        raise not_found("BoosterIncident not found.")
    if inc["status"] != "INVESTIGATING":
        raise invalid_state("BoosterIncident is not in INVESTIGATING state.")
    inc["status"] = "DISMISSED"
    db.stamp_update(inc)
    return ok_object(inc)
