"""Campaign endpoints and lifecycle (PRD 3.3, 3.7, 3.10)."""
from flask import Blueprint, request

import db
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_enum, require_int,
                    require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services import ledger
from services.cascades import archive_campaign_cascade
from services.serialize import campaign_out

bp = Blueprint("campaigns", __name__)

OBJECTIVES = {"LAUNCH", "THOUGHT_LEADERSHIP", "CRISIS", "AWARENESS"}
BEATS = {"TECH", "HEALTH", "FINANCE", "CONSUMER", "POLITICS"}
CAMPAIGN_STATUSES = {"DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED"}


@bp.post("/agency/campaigns")
@authorize(["AccountManager"])
def create_campaign():
    body = get_json_body()
    client_id = body.get("client_id")
    ref_or_404(db.clients, client_id, "client_id")
    title = require_str(body, "title")
    objective = require_enum(body, "objective", OBJECTIVES)
    budget_cents = require_int(body, "budget_cents", minimum=1)  # > 0
    target_beat = require_enum(body, "target_beat", BEATS)

    rec = new_record({
        "client_id": client_id,
        "title": title,
        "objective": objective,
        "budget_cents": budget_cents,
        "target_beat": target_beat,
        "status": "DRAFT",
        "earned_media_value_cents": 0,
        "cost_basis_cents": 0,
        "roi_ratio": None,
    })
    db.campaigns[rec["id"]] = rec
    return success(campaign_out(rec), status=201)


@bp.get("/agency/campaigns/<campaign_id>")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def get_campaign(campaign_id):
    rec = get_or_404(db.campaigns, campaign_id)
    return success(campaign_out(rec))


@bp.get("/agency/campaigns")
@authorize(["AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"])
def list_campaigns():
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    if status is not None and status not in CAMPAIGN_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.campaigns.values():
        if client_id is not None and r["client_id"] != client_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([campaign_out(r) for r in page], pagination=meta)


@bp.post("/agency/campaigns/<campaign_id>/activate")
@authorize(["AccountManager"])
def activate_campaign(campaign_id):
    rec = get_or_404(db.campaigns, campaign_id)
    if rec["status"] not in ("DRAFT", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Campaign cannot be activated from its current state")
    client = db.clients[rec["client_id"]]
    if client["status"] != "ACTIVE":
        raise err("ERR_CLIENT_SUSPENDED", "Owning client is suspended")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(campaign_out(rec))


@bp.post("/agency/campaigns/<campaign_id>/pause")
@authorize(["AccountManager"])
def pause_campaign(campaign_id):
    rec = get_or_404(db.campaigns, campaign_id)
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Campaign is not ACTIVE")
    rec["status"] = "PAUSED"
    touch(rec)
    return success(campaign_out(rec))


@bp.post("/agency/campaigns/<campaign_id>/complete")
@authorize(["AccountManager"])
def complete_campaign(campaign_id):
    rec = get_or_404(db.campaigns, campaign_id)
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Campaign cannot be completed from its current state")
    # Preconditions evaluated together; open-pitch guard first per scaffold order.
    has_open_pitch = any(
        p["campaign_id"] == rec["id"] and p["status"] in ("SENT", "RESPONDED")
        for p in db.pitches.values())
    if has_open_pitch:
        raise err("ERR_CAMPAIGN_HAS_OPEN_PITCHES",
                  "Campaign has open pitches in SENT or RESPONDED")
    has_open_interview = any(
        i["campaign_id"] == rec["id"] and i["status"] in ("REQUESTED", "CONFIRMED")
        for i in db.interviews.values())
    if has_open_interview:
        raise err("ERR_CAMPAIGN_HAS_OPEN_INTERVIEWS",
                  "Campaign has open interviews in REQUESTED or CONFIRMED")
    rec["status"] = "COMPLETED"
    # Recompute roi once more so the closed campaign carries a settled ratio.
    ledger.recompute_campaign_ledger(rec)
    touch(rec)
    return success(campaign_out(rec))


@bp.post("/agency/campaigns/<campaign_id>/archive")
@authorize(["AccountManager"])
def archive_campaign(campaign_id):
    rec = get_or_404(db.campaigns, campaign_id)
    if rec["status"] not in ("DRAFT", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "Campaign cannot be archived from its current state")
    rec["status"] = "ARCHIVED"
    touch(rec)
    archive_campaign_cascade(rec)
    return success(campaign_out(rec))
