"""Diagnostic team registration endpoints (PRD §3.2)."""
import uuid

from flask import Blueprint

from db import now_iso, store
from errors import ERR_TEAM_NOT_FOUND
from helpers import body_or_empty, get_or_404, reject_unknown, req_str
from middleware import auth
from response import ok

bp = Blueprint("diagnostic_teams", __name__)

ALL_ROLES = ("ProgramAdministrator", "RailSafetyOfficer", "LocalAuthority", "RailroadMaintainer")


def serialize_team(rec):
    return {
        "id": rec["id"],
        "team_name": rec["team_name"],
        "lead_agency": rec["lead_agency"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/diagnostic-teams")
def create_team():
    auth(["ProgramAdministrator"])
    body = body_or_empty()
    reject_unknown(body, ("team_name", "lead_agency"))
    ts = now_iso()
    rec = {
        "id": str(uuid.uuid4()),
        "team_name": req_str(body, "team_name"),
        "lead_agency": req_str(body, "lead_agency"),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.teams[rec["id"]] = rec
    return ok(serialize_team(rec), 201)


@bp.get("/diagnostic-teams/<team_id>")
def get_team(team_id):
    auth(ALL_ROLES)
    rec = get_or_404(store.teams, team_id, ERR_TEAM_NOT_FOUND,
                     f"Diagnostic team {team_id} does not exist")
    return ok(serialize_team(rec))
