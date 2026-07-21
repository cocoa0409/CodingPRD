"""Incentive tier and award endpoints (PRD 3.6)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("incentives", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
AWARD_STATUSES = ["EARNED", "FULFILLED", "REVOKED"]


@bp.post("/api/incentive-tiers")
def create_tier():
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    name = v.req_str(body, "name")
    threshold_cents = v.req_int(body, "threshold_cents", minimum=1)
    reward_description = v.req_str(body, "reward_description")
    campaign = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, campaign)
    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")
    rec = db.new_record(
        campaign_id=campaign_id,
        name=name,
        threshold_cents=threshold_cents,
        reward_description=reward_description,
    )
    store.incentive_tiers[rec["id"]] = rec
    return response.object_response(domain.ser_tier(rec), 201)


@bp.get("/api/incentive-tiers/<tier_id>")
def read_tier(tier_id):
    authorize(PUBLIC)
    rec = domain.get_tier(tier_id)
    return response.object_response(domain.ser_tier(rec))


@bp.get("/api/incentive-tiers")
def list_tiers():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    rows = list(store.incentive_tiers.values())
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    return response.paged(rows, domain.ser_tier, limit, offset)


@bp.get("/api/incentive-awards/<award_id>")
def read_award(award_id):
    authorize(PUBLIC)
    rec = domain.get_award(award_id)
    return response.object_response(domain.ser_award(rec))


@bp.get("/api/incentive-awards")
def list_awards():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    participant_id = v.q("participant_id")
    tier_id = v.q("tier_id")
    status = v.q_enum("status", AWARD_STATUSES)
    rows = list(store.incentive_awards.values())
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    if tier_id is not None:
        rows = [r for r in rows if r["tier_id"] == tier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_award, limit, offset)


@bp.post("/api/incentive-awards/<award_id>/fulfill")
def fulfill_award(award_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_award(award_id)
    participant = store.participants.get(rec["participant_id"])
    if participant is not None:
        campaign = domain.campaign_of_participant(participant)
        if campaign is not None:
            domain.require_manager_owns_campaign(user_id, campaign)
    if rec["status"] != "EARNED":
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "FULFILLED"
    rec["fulfilled_at"] = db.now_iso()
    db.touch(rec)
    return response.object_response(domain.ser_award(rec))
