"""Education campaign + outreach event endpoints."""
import uuid

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CAMPAIGN_WINDOW_CONFLICT,
    ERR_OUTSIDE_CAMPAIGN_WINDOW,
    ERR_CAMPAIGN_BUDGET_EXCEEDED,
)
from middleware import auth, require_roles, get_or_404, paginate, by_creation, filter_enum
from response import success
from services.calculations import campaign_remaining_budget, CAMPAIGN_ZONE_BUFFER
from services.serializers import ser_campaign, ser_outreach_event
from validation import body_json, v_str, v_int, v_dt

bp = Blueprint("campaigns", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer"]
EVENT_STATUSES = ("RECORDED", "VOIDED")


@bp.post("/campaigns")
def create_campaign():
    uid, role = auth()
    body = body_json()
    name = v_str(body, "name")
    zone = v_str(body, "outreach_zone")
    start = v_dt(body, "start_date")
    end = v_dt(body, "end_date")
    if not end > start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "end_date must be after start_date")
    budget = v_int(body, "budget_cents", min_val=0)
    require_roles(role, ["ProgramAdmin"])
    for other in STORE["campaigns"].values():
        if other["outreach_zone"] != zone:
            continue
        # Conflict when windows overlap or sit within 14 days of each other.
        if start < other["end_date"] + CAMPAIGN_ZONE_BUFFER and other["start_date"] < end + CAMPAIGN_ZONE_BUFFER:
            raise ApiError(
                ERR_CAMPAIGN_WINDOW_CONFLICT,
                409,
                "Campaign window overlaps or sits within 14 days of another campaign in the same zone",
            )
    current = now()
    c = {
        "id": str(uuid.uuid4()),
        "name": name,
        "outreach_zone": zone,
        "start_date": start,
        "end_date": end,
        "budget_cents": budget,
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["campaigns"][c["id"]] = c
    return success(ser_campaign(c), 201)


@bp.get("/campaigns/<cid>")
def get_campaign(cid):
    uid, role = auth()
    require_roles(role, READERS)
    c = get_or_404("campaigns", cid)
    return success(ser_campaign(c))


@bp.post("/campaigns/<cid>/events")
def create_outreach_event(cid):
    uid, role = auth()
    body = body_json()
    event_date = v_dt(body, "event_date")
    venue = v_str(body, "venue_name")
    attendance = v_int(body, "attendance_count", min_val=0)
    cost = v_int(body, "cost_cents", min_val=0)
    require_roles(role, ["ProgramAdmin"])
    campaign = get_or_404("campaigns", cid)
    # Temporal rule before the fiscal rule (PRD §2.9).
    if not (campaign["start_date"] <= event_date <= campaign["end_date"]):
        raise ApiError(ERR_OUTSIDE_CAMPAIGN_WINDOW, 422, "event_date falls outside the campaign window")
    if cost > campaign_remaining_budget(campaign):
        raise ApiError(ERR_CAMPAIGN_BUDGET_EXCEEDED, 422, "cost_cents exceeds the campaign's remaining budget")
    current = now()
    e = {
        "id": str(uuid.uuid4()),
        "campaign_id": cid,
        "event_date": event_date,
        "venue_name": venue,
        "attendance_count": attendance,
        "cost_cents": cost,
        "status": "RECORDED",
        "created_at": current,
        "updated_at": current,
        "version": 1,
        "_seq": next_seq(),
    }
    STORE["outreach_events"][e["id"]] = e
    return success(ser_outreach_event(e), 201)


@bp.get("/outreach-events")
def list_outreach_events():
    uid, role = auth()
    require_roles(role, READERS)
    campaign_filter = request.args.get("campaign_id")
    status_filter = filter_enum(request.args, "status", EVENT_STATUSES)
    items = list(STORE["outreach_events"].values())
    if campaign_filter is not None:
        items = [e for e in items if e["campaign_id"] == campaign_filter]
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_outreach_event(e) for e in page], 200, "array", meta)


@bp.get("/outreach-events/<oid>")
def get_outreach_event(oid):
    uid, role = auth()
    require_roles(role, READERS)
    e = get_or_404("outreach_events", oid)
    return success(ser_outreach_event(e))


@bp.post("/outreach-events/<oid>/void")
def void_outreach_event(oid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    e = get_or_404("outreach_events", oid)
    if e["status"] != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Outreach event is not in RECORDED status")
    e["status"] = "VOIDED"
    e["updated_at"] = now()
    e["version"] += 1
    return success(ser_outreach_event(e))
