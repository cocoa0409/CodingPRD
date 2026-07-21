"""Team endpoints (PRD 3.2, 3.8)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("teams", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
TEAM_STATUSES = ["ACTIVE", "DISBANDED"]


@bp.post("/api/teams")
def create_team():
    user_id, role = authorize([config.ROLE_CAMPAIGN_MANAGER, config.ROLE_PARTICIPANT])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    name = v.req_str(body, "name")
    goal_amount_cents = v.req_int(body, "goal_amount_cents", minimum=1)
    captain_participant_id = v.opt_str(body, "captain_participant_id")
    campaign = domain.get_campaign(campaign_id)
    captain = None
    if captain_participant_id is not None:
        captain = domain.get_participant(captain_participant_id)
    domain.require_actor_owns_campaign(user_id, role, campaign)
    # PRD 2.7: a captain must belong to the same campaign.
    if captain is not None and captain["campaign_id"] != campaign_id:
        raise_error("ERR_TEAM_CAMPAIGN_MISMATCH")
    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")
    rec = db.new_record(
        campaign_id=campaign_id,
        name=name,
        goal_amount_cents=goal_amount_cents,
        captain_participant_id=captain_participant_id,
        status="ACTIVE",
        credited_cents=0,
        member_count=0,
    )
    store.teams[rec["id"]] = rec
    return response.object_response(domain.ser_team(rec), 201)


@bp.get("/api/teams/<team_id>")
def read_team(team_id):
    authorize(PUBLIC)
    rec = domain.get_team(team_id)
    return response.object_response(domain.ser_team(rec))


@bp.get("/api/teams")
def list_teams():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    captain_participant_id = v.q("captain_participant_id")
    status = v.q_enum("status", TEAM_STATUSES)
    rows = list(store.teams.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if captain_participant_id is not None:
        rows = [
            r for r in rows if r["captain_participant_id"] == captain_participant_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_team, limit, offset)


@bp.post("/api/teams/<team_id>/disband")
def disband_team(team_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_team(team_id)
    campaign = store.campaigns.get(rec["campaign_id"])
    if campaign is not None:
        domain.require_manager_owns_campaign(user_id, campaign)
    if rec["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "DISBANDED"
    members = [p for p in store.participants.values() if p["team_id"] == team_id]
    for participant in db.ordered(members):
        participant["team_id"] = None
        db.touch(participant)
        domain.refresh_participant(participant)
    db.touch(rec)
    return response.object_response(domain.ser_team(rec))
