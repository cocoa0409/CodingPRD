"""Athletes: enroll, list, get (with CoachingStaff masking), roster actions."""
from flask import Blueprint, request

from db import STORE, new_id, now_stamp, touch
from errors import not_found, conflict, ERR_ATHLETE_NOT_ACTIVE, \
    ERR_ATHLETE_NOT_INACTIVE, ERR_OPEN_CASES_EXIST
from middleware import require_roles
from response import ok_obj, ok_list
from routes.serializers import athlete_json, sorted_items
from services.common import find_all
from services.derived import recompute_athlete
from util import body, present, require_str, require_date

bp = Blueprint("athletes", __name__)

ALL_ROLES = ("TeamAdmin", "MedicalStaff", "TeamPhysician",
             "PerformanceStaff", "BillingStaff", "CoachingStaff")
NON_TERMINAL_CASE_STATES = {"OPEN", "REHAB", "RTP", "LONG_TERM"}


def _get_athlete(athlete_id):
    a = STORE["athletes"].get(athlete_id)
    if a is None:
        raise not_found("Athlete not found")
    return a


@bp.route("/athletes", methods=["POST"])
def create_athlete():
    require_roles("TeamAdmin")
    j = body()
    # existence (3): team FK if provided
    team = None
    if present(j, "team_id"):
        team = STORE["teams"].get(j["team_id"])
        if team is None:
            raise not_found("Team not found: team_id")
    # field constraints (10)
    if team is None:
        require_str(j, "team_id")  # raises 400 missing
    full_name = require_str(j, "full_name")
    position = require_str(j, "position")
    eraw, edate = require_date(j, "enrollment_date")
    ts = now_stamp()
    athlete = {
        "id": new_id(), "team_id": team["id"], "full_name": full_name,
        "position": position, "enrollment_date": eraw, "_enrollment_date": edate,
        "roster_status": "ACTIVE", "availability_tier": "FULL",
        "acute_chronic_workload_ratio": None, "load_flag": "NONE",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    STORE["athletes"][athlete["id"]] = athlete
    return ok_obj(athlete_json(athlete), 201)


@bp.route("/athletes", methods=["GET"])
def list_athletes():
    _, role = require_roles(*ALL_ROLES)
    items = sorted_items(STORE["athletes"])
    team_id = request.args.get("team_id")
    roster_status = request.args.get("roster_status")
    position = request.args.get("position")
    if team_id is not None:
        items = [a for a in items if a["team_id"] == team_id]
    if roster_status is not None:
        items = [a for a in items if a["roster_status"] == roster_status]
    if position is not None:
        items = [a for a in items if a["position"] == position]
    return ok_list([athlete_json(a, role) for a in items])


@bp.route("/athletes/<athleteId>", methods=["GET"])
def get_athlete(athleteId):
    _, role = require_roles(*ALL_ROLES)
    return ok_obj(athlete_json(_get_athlete(athleteId), role))


@bp.route("/athletes/<athleteId>/deactivate", methods=["POST"])
def deactivate_athlete(athleteId):
    require_roles("TeamAdmin")
    a = _get_athlete(athleteId)
    if a["roster_status"] != "ACTIVE":
        raise conflict(ERR_ATHLETE_NOT_ACTIVE, "Athlete is not ACTIVE")
    a["roster_status"] = "INACTIVE"
    touch(a)
    return ok_obj(athlete_json(a))


@bp.route("/athletes/<athleteId>/reactivate", methods=["POST"])
def reactivate_athlete(athleteId):
    require_roles("TeamAdmin")
    a = _get_athlete(athleteId)
    if a["roster_status"] != "INACTIVE":
        raise conflict(ERR_ATHLETE_NOT_INACTIVE, "Athlete is not INACTIVE")
    a["roster_status"] = "ACTIVE"
    recompute_athlete(a, bump=True)
    return ok_obj(athlete_json(a))


@bp.route("/athletes/<athleteId>/release", methods=["POST"])
def release_athlete(athleteId):
    require_roles("TeamAdmin")
    a = _get_athlete(athleteId)
    if a["roster_status"] != "ACTIVE":
        raise conflict(ERR_ATHLETE_NOT_ACTIVE, "Athlete is not ACTIVE")
    open_cases = find_all("injury_cases",
                          lambda c: c["athlete_id"] == a["id"]
                          and c["status"] in NON_TERMINAL_CASE_STATES)
    if open_cases:
        raise conflict(ERR_OPEN_CASES_EXIST,
                       "Athlete has non-terminal injury cases")
    a["roster_status"] = "RELEASED"
    # cascade: all ACTIVE DisclosureGrants for athlete -> REVOKED
    for g in find_all("disclosure_grants", lambda g: g["athlete_id"] == a["id"]):
        if g["status"] == "ACTIVE":
            g["status"] = "REVOKED"
            touch(g)
    touch(a)
    return ok_obj(athlete_json(a))
