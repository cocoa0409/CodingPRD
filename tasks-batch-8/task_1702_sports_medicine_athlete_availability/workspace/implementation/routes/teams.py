"""Clock, Teams, Diagnosis codes."""
from flask import Blueprint

from db import STORE, new_id, now_stamp, clock_raw, set_clock, parse_iso_dt
from errors import bad_request, not_found
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import team_json, diagnosis_code_json, sorted_items
from util import body, present, require_str, optional_enum, require_enum, require_date, require_bool

bp = Blueprint("teams", __name__)

SPORTS = ["FOOTBALL", "BASKETBALL", "SOCCER", "HOCKEY", "BASEBALL"]
HIPAA_MODES = ["STRICT", "STANDARD"]
ACWR_VARIANTS = ["ROLLING", "EWMA"]
BODY_REGIONS = ["HEAD_NECK", "SHOULDER", "ARM", "HAND", "TRUNK", "HIP",
                "KNEE", "LOWER_LEG", "ANKLE_FOOT", "SYSTEMIC"]
SEVERITY_CLASSES = ["MINOR", "MODERATE", "SEVERE"]
ALL_ROLES = ("TeamAdmin", "MedicalStaff", "TeamPhysician",
             "PerformanceStaff", "BillingStaff", "CoachingStaff")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("TeamAdmin")
    j = body()
    if not present(j, "to_iso8601") or not isinstance(j["to_iso8601"], str):
        raise bad_request("Missing required field: to_iso8601")
    raw = j["to_iso8601"]
    if parse_iso_dt(raw) is None:
        raise bad_request("Invalid ISO8601 timestamp: to_iso8601")
    set_clock(raw)
    return ok_obj({"current_utc": raw}, 200)


@bp.route("/teams", methods=["POST"])
def create_team():
    require_roles("TeamAdmin")
    j = body()
    name = require_str(j, "name")
    sport = require_enum(j, "sport", SPORTS)
    sraw, sdate = require_date(j, "season_start_date")
    eraw, edate = require_date(j, "season_end_date")
    if edate <= sdate:
        raise bad_request("season_end_date must be later than season_start_date")
    hipaa = optional_enum(j, "hipaa_mode", HIPAA_MODES, "STRICT")
    variant = optional_enum(j, "acwr_variant", ACWR_VARIANTS, "ROLLING")
    ts = now_stamp()
    team = {
        "id": new_id(), "name": name, "sport": sport,
        "season_start_date": sraw, "season_end_date": eraw,
        "hipaa_mode": hipaa, "acwr_variant": variant,
        "current_utc": clock_raw(),
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["teams"][team["id"]] = team
    return ok_obj(team_json(team), 201)


@bp.route("/teams", methods=["GET"])
def list_teams():
    require_roles(*ALL_ROLES)
    return ok_list([team_json(t) for t in sorted_items(STORE["teams"])])


@bp.route("/teams/<teamId>", methods=["GET"])
def get_team(teamId):
    require_roles(*ALL_ROLES)
    team = STORE["teams"].get(teamId)
    if team is None:
        raise not_found("Team not found")
    return ok_obj(team_json(team))


@bp.route("/diagnosis-codes", methods=["POST"])
def create_diagnosis_code():
    require_roles("TeamAdmin")
    j = body()
    code = require_str(j, "code")
    region = require_enum(j, "body_region", BODY_REGIONS)
    severity = require_enum(j, "severity_class", SEVERITY_CLASSES)
    is_conc = require_bool(j, "is_concussion")
    for d in STORE["diagnosis_codes"].values():
        if d["code"] == code:
            raise bad_request("Diagnosis code already exists: %s" % code)
    ts = now_stamp()
    dc = {
        "id": new_id(), "code": code, "body_region": region,
        "severity_class": severity, "is_concussion": is_conc,
        "created_at": ts,
    }
    STORE["diagnosis_codes"][dc["id"]] = dc
    return ok_obj(diagnosis_code_json(dc), 201)


@bp.route("/diagnosis-codes", methods=["GET"])
def list_diagnosis_codes():
    require_roles("TeamAdmin", "MedicalStaff", "TeamPhysician")
    return ok_list([diagnosis_code_json(d) for d in sorted_items(STORE["diagnosis_codes"])])


@bp.route("/diagnosis-codes/<codeId>", methods=["GET"])
def get_diagnosis_code(codeId):
    require_roles("TeamAdmin", "MedicalStaff", "TeamPhysician")
    dc = STORE["diagnosis_codes"].get(codeId)
    if dc is None:
        raise not_found("DiagnosisCode not found")
    return ok_obj(diagnosis_code_json(dc))
