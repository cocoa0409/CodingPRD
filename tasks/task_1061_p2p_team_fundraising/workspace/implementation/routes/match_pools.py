"""Sponsor match pool endpoints (PRD 3.5)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("match_pools", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
POOL_STATUSES = ["ACTIVE", "EXHAUSTED", "CLOSED"]


@bp.post("/api/match-pools")
def create_match_pool():
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    sponsor_name = v.req_str(body, "sponsor_name")
    pool_amount_cents = v.req_int(body, "pool_amount_cents", minimum=1)
    match_ratio = v.req_number(body, "match_ratio", gt=0, lte=5)
    per_donation_cap_cents = v.req_int(body, "per_donation_cap_cents", minimum=1)
    starts_at = v.req_dt(body, "starts_at")
    ends_at = v.req_dt(body, "ends_at")
    min_donation_cents = v.opt_int(body, "min_donation_cents", default=0, minimum=0)
    if not ends_at > starts_at:
        raise_error(
            "ERR_INVALID_REQUEST", "Field 'ends_at' must be strictly after 'starts_at'."
        )
    campaign = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, campaign)

    # PRD 3.5: half-open windows of live pools may not overlap.
    for pool in domain.campaign_pools(campaign_id):
        domain.refresh_pool(pool)
        if pool["status"] not in ("ACTIVE", "EXHAUSTED"):
            continue
        existing_start = db.dt_of(pool["starts_at"])
        existing_end = db.dt_of(pool["ends_at"])
        if starts_at < existing_end and existing_start < ends_at:
            raise_error("ERR_MATCH_WINDOW_OVERLAP")

    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")

    rec = db.new_record(
        campaign_id=campaign_id,
        sponsor_name=sponsor_name,
        pool_amount_cents=pool_amount_cents,
        match_ratio=match_ratio,
        per_donation_cap_cents=per_donation_cap_cents,
        min_donation_cents=min_donation_cents,
        starts_at=db.iso(starts_at),
        ends_at=db.iso(ends_at),
        allocated_cents=0,
        remaining_cents=pool_amount_cents,
        status="ACTIVE",
    )
    store.match_pools[rec["id"]] = rec
    return response.object_response(domain.ser_match_pool(rec), 201)


@bp.get("/api/match-pools/<pool_id>")
def read_match_pool(pool_id):
    authorize(PUBLIC)
    rec = domain.get_match_pool(pool_id)
    return response.object_response(domain.ser_match_pool(rec))


@bp.get("/api/match-pools")
def list_match_pools():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    status = v.q_enum("status", POOL_STATUSES)
    rows = list(store.match_pools.values())
    for rec in rows:
        domain.refresh_pool(rec)
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_match_pool, limit, offset)


@bp.post("/api/match-pools/<pool_id>/close")
def close_match_pool(pool_id):
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    rec = domain.get_match_pool(pool_id)
    campaign = store.campaigns.get(rec["campaign_id"])
    if campaign is not None:
        domain.require_manager_owns_campaign(user_id, campaign)
    domain.refresh_pool(rec)
    if rec["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise_error("ERR_INVALID_STATE")
    rec["status"] = "CLOSED"
    db.touch(rec)
    return response.object_response(domain.ser_match_pool(rec))
