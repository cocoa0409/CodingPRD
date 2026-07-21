"""Participant (fundraiser page) endpoints (PRD 3.2)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("participants", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
PARTICIPANT_STATUSES = ["PENDING", "ACTIVE", "WITHDRAWN"]


def _authorize_participant_action(user_id, role, participant):
    if role == config.ROLE_PARTICIPANT:
        domain.require_participant_is(user_id, participant)
    elif role == config.ROLE_CAMPAIGN_MANAGER:
        campaign = domain.campaign_of_participant(participant)
        if campaign is not None:
            domain.require_manager_owns_campaign(user_id, campaign)


@bp.post("/api/participants")
def create_participant():
    user_id, role = authorize([config.ROLE_ANONYMOUS, config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    display_name = v.req_str(body, "display_name")
    team_id = v.opt_str(body, "team_id")
    recruited_by_participant_id = v.opt_str(body, "recruited_by_participant_id")
    personal_goal_cents = v.opt_int(
        body, "personal_goal_cents", default=10000, minimum=1
    )
    campaign = domain.get_campaign(campaign_id)
    team = domain.get_team(team_id) if team_id is not None else None
    recruiter = (
        domain.get_participant(recruited_by_participant_id)
        if recruited_by_participant_id is not None
        else None
    )
    domain.require_actor_owns_campaign(user_id, role, campaign)
    # PRD 2.7 / 3.2 referential guards.
    if team is not None and team["campaign_id"] != campaign_id:
        raise_error("ERR_TEAM_CAMPAIGN_MISMATCH")
    if recruiter is not None and recruiter["campaign_id"] != campaign_id:
        raise_error("ERR_SELF_RECRUIT")
    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")

    rec = db.new_record(
        campaign_id=campaign_id,
        team_id=team_id,
        recruited_by_participant_id=recruited_by_participant_id,
        display_name=display_name,
        personal_goal_cents=personal_goal_cents,
        status="PENDING",
        credited_cents=0,
        projected_cents=0,
        recruit_count=0,
        minimum_met=False,
    )
    store.participants[rec["id"]] = rec
    if team is not None:
        db.touch(team)
        domain.refresh_team(team)
    if recruiter is not None:
        db.touch(recruiter)
        domain.refresh_participant(recruiter)
    return response.object_response(domain.ser_participant(rec), 201)


@bp.get("/api/participants/<participant_id>")
def read_participant(participant_id):
    authorize(PUBLIC)
    rec = domain.get_participant(participant_id)
    return response.object_response(domain.ser_participant(rec))


@bp.get("/api/participants")
def list_participants():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    team_id = v.q("team_id")
    recruited_by_participant_id = v.q("recruited_by_participant_id")
    status = v.q_enum("status", PARTICIPANT_STATUSES)
    rows = list(store.participants.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if team_id is not None:
        rows = [r for r in rows if r["team_id"] == team_id]
    if recruited_by_participant_id is not None:
        rows = [
            r
            for r in rows
            if r["recruited_by_participant_id"] == recruited_by_participant_id
        ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_participant, limit, offset)


@bp.post("/api/participants/<participant_id>/activate")
def activate_participant(participant_id):
    user_id, role = authorize([config.ROLE_PARTICIPANT, config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_participant(participant_id)
    _authorize_participant_action(user_id, role, rec)
    if rec["status"] != "PENDING":
        raise_error("ERR_INVALID_STATE")
    campaign = domain.campaign_of_participant(rec)
    if campaign is None or campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return response.object_response(domain.ser_participant(rec))


@bp.post("/api/participants/<participant_id>/withdraw")
def withdraw_participant(participant_id):
    user_id, role = authorize([config.ROLE_PARTICIPANT, config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_participant(participant_id)
    _authorize_participant_action(user_id, role, rec)
    if rec["status"] not in ("PENDING", "ACTIVE"):
        raise_error("ERR_INVALID_STATE")

    was_active = rec["status"] == "ACTIVE"
    rec["status"] = "WITHDRAWN"
    db.touch(rec)

    if was_active:
        # Cascade step 1: open registrations become CANCELLED.
        touched_events = []
        for registration in db.ordered(domain.participant_registrations(participant_id)):
            if registration["status"] not in ("RESERVED", "CONFIRMED"):
                continue
            registration["status"] = "CANCELLED"
            db.touch(registration)
            event = store.events.get(registration["event_id"])
            if event is not None and event not in touched_events:
                touched_events.append(event)
        # Cascade steps 2 and 3: counts fall, FULL events re-open.
        for event in touched_events:
            domain.refresh_event(event)
            db.touch(event)

    team = store.teams.get(rec["team_id"]) if rec["team_id"] else None
    if team is not None:
        db.touch(team)
        domain.refresh_team(team)

    return response.object_response(domain.ser_participant(rec))
