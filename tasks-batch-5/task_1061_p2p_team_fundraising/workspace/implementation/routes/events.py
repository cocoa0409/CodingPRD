"""Event endpoints (PRD 3.3)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from errors import raise_error
from services import domain

bp = Blueprint("events", __name__)

PUBLIC = config.PUBLIC_READ_ROLES
EVENT_STATUSES = ["OPEN", "FULL", "CLOSED"]


@bp.post("/api/events")
def create_event():
    user_id, _role = authorize([config.ROLE_CAMPAIGN_MANAGER])
    body = v.get_body()
    campaign_id = v.req_str(body, "campaign_id")
    name = v.req_str(body, "name")
    starts_at = v.req_dt(body, "starts_at")
    ends_at = v.req_dt(body, "ends_at")
    early_bird_ends_at = v.req_dt(body, "early_bird_ends_at")
    registration_fee_cents = v.req_int(body, "registration_fee_cents", minimum=0)
    capacity = v.req_int(body, "capacity", minimum=1)
    if not ends_at > starts_at:
        raise_error(
            "ERR_INVALID_REQUEST", "Field 'ends_at' must be strictly after 'starts_at'."
        )
    campaign = domain.get_campaign(campaign_id)
    domain.require_manager_owns_campaign(user_id, campaign)
    if campaign["status"] != "PUBLISHED":
        raise_error("ERR_CAMPAIGN_NOT_PUBLISHED")
    rec = db.new_record(
        campaign_id=campaign_id,
        name=name,
        starts_at=db.iso(starts_at),
        ends_at=db.iso(ends_at),
        early_bird_ends_at=db.iso(early_bird_ends_at),
        registration_fee_cents=registration_fee_cents,
        capacity=capacity,
        registered_count=0,
        status="OPEN",
    )
    store.events[rec["id"]] = rec
    return response.object_response(domain.ser_event(rec), 201)


@bp.get("/api/events/<event_id>")
def read_event(event_id):
    authorize(PUBLIC)
    rec = domain.get_event(event_id)
    return response.object_response(domain.ser_event(rec))


@bp.get("/api/events")
def list_events():
    authorize(PUBLIC)
    limit, offset = v.pagination()
    campaign_id = v.q("campaign_id")
    status = v.q_enum("status", EVENT_STATUSES)
    rows = list(store.events.values())
    for rec in rows:
        domain.refresh_event(rec)
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paged(rows, domain.ser_event, limit, offset)
