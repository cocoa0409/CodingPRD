"""Team endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from validate import get_body, validate_body

bp = Blueprint("teams", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_team(team_id):
    t = store.teams.get(team_id)
    if t is None:
        raise err_not_found("team")
    return t


@bp.post("/v1/teams")
def create_team():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {
        "animal_id": ("string", True, None),
        "team_name": ("string", True, None),
    })
    animal = store.animals.get(body["animal_id"])
    if animal is None:
        raise err_not_found("animal")
    if animal["handler_id"] != auth.user_id:
        raise err_ownership()
    for team in store.teams.values():
        if team["animal_id"] == animal["id"] and team["status"] in ("FORMING", "ACTIVE", "SUSPENDED"):
            raise err("ERR_ACTIVE_TEAM_EXISTS", 422,
                      "Animal already belongs to a non-dissolved team")
    rec = new_record(store.teams, {
        "handler_id": auth.user_id,
        "animal_id": animal["id"],
        "team_name": body["team_name"],
        "status": "FORMING",
        "late_cancel_count": 0,
        "no_show_count": 0,
        "warning_count": 0,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/teams/<team_id>")
def get_team(team_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_team(team_id)), 200)


@bp.get("/v1/teams")
def list_teams():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.teams.values())
    handler_id = request.args.get("handler_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    if handler_id is not None:
        records = [r for r in records if r["handler_id"] == handler_id]
    if animal_id is not None:
        records = [r for r in records if r["animal_id"] == animal_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/teams/<team_id>/dissolve")
def dissolve_team(team_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    team = _get_team(team_id)
    if team["handler_id"] != auth.user_id:
        raise err_ownership()
    if team["status"] == "DISSOLVED":
        # Already terminal: no defined transition; treat as state error.
        raise err("ERR_TEAM_NOT_ACTIVE", 409, "Team is already DISSOLVED")
    for v in store.visits.values():
        if v["team_id"] == team["id"] and v["lifecycle_status"] in ("SCHEDULED", "IN_PROGRESS"):
            raise err("ERR_TEAM_HAS_SCHEDULED_VISITS", 409,
                      "Team has visits in SCHEDULED or IN_PROGRESS")
    for c in store.certifications.values():
        if c["team_id"] == team["id"] and c["status"] in ("PROVISIONAL", "ACTIVE", "RENEWAL_DUE", "SUSPENDED"):
            raise err("ERR_TEAM_HAS_ACTIVE_CERTIFICATION", 409,
                      "Team has a non-terminal certification")
    team["status"] = "DISSOLVED"
    touch(team)
    return success_object(public(team), 200)
