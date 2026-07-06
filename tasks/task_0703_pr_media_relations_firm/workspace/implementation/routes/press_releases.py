"""PressRelease endpoints and lifecycle (PRD 3.5)."""
from flask import Blueprint, request

import db
from clock import clock
from common import (get_json_body, get_or_404, new_record, paginate, parse_dt,
                    parse_pagination, ref_or_404, require_datetime, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import press_release_out

bp = Blueprint("press_releases", __name__)

PRESS_RELEASE_STATUSES = {"DRAFT", "SCHEDULED", "RELEASED", "WITHDRAWN"}


@bp.post("/agency/press-releases")
@authorize(["MediaSpecialist"])
def create_press_release():
    body = get_json_body()
    campaign_id = body.get("campaign_id")
    ref_or_404(db.campaigns, campaign_id, "campaign_id")
    headline = require_str(body, "headline")
    embargo_until = require_datetime(body, "embargo_until")

    rec = new_record({
        "campaign_id": campaign_id,
        "headline": headline,
        "embargo_until": body["embargo_until"],
        "status": "DRAFT",
        "released_at": None,
    })
    db.press_releases[rec["id"]] = rec
    return success(press_release_out(rec), status=201)


@bp.get("/agency/press-releases/<press_release_id>")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def get_press_release(press_release_id):
    rec = get_or_404(db.press_releases, press_release_id)
    return success(press_release_out(rec))


@bp.get("/agency/press-releases")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def list_press_releases():
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    if status is not None and status not in PRESS_RELEASE_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.press_releases.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([press_release_out(r) for r in page], pagination=meta)


@bp.post("/agency/press-releases/<press_release_id>/schedule")
@authorize(["MediaSpecialist"])
def schedule_press_release(press_release_id):
    rec = get_or_404(db.press_releases, press_release_id)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Press release is not DRAFT")
    campaign = db.campaigns[rec["campaign_id"]]
    if campaign["status"] != "ACTIVE":
        raise err("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    embargo = parse_dt(rec["embargo_until"])
    if embargo <= clock.now():
        raise err("ERR_EMBARGO_IN_PAST", "embargo_until is at or before the current clock")
    rec["status"] = "SCHEDULED"
    touch(rec)
    return success(press_release_out(rec))


@bp.post("/agency/press-releases/<press_release_id>/release")
@authorize(["MediaSpecialist"])
def release_press_release(press_release_id):
    rec = get_or_404(db.press_releases, press_release_id)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Press release is not SCHEDULED")
    embargo = parse_dt(rec["embargo_until"])
    if clock.now() < embargo:
        raise err("ERR_EMBARGO_NOT_LIFTED", "Embargo has not lifted")
    dists = [d for d in db.distributions.values() if d["press_release_id"] == rec["id"]]
    if not dists:
        raise err("ERR_NO_DISTRIBUTIONS", "No distributions exist for this release")
    rec["status"] = "RELEASED"
    rec["released_at"] = clock.now_iso()
    touch(rec)
    for d in dists:
        if d["status"] == "QUEUED":
            d["status"] = "DELIVERED"
            d["delivered_at"] = clock.now_iso()
            touch(d)
    return success(press_release_out(rec))


@bp.post("/agency/press-releases/<press_release_id>/withdraw")
@authorize(["MediaSpecialist"])
def withdraw_press_release(press_release_id):
    rec = get_or_404(db.press_releases, press_release_id)
    if rec["status"] not in ("DRAFT", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Press release cannot be withdrawn from its current state")
    was_scheduled = rec["status"] == "SCHEDULED"
    rec["status"] = "WITHDRAWN"
    touch(rec)
    if was_scheduled:
        for d in db.distributions.values():
            if d["press_release_id"] == rec["id"] and d["status"] == "QUEUED":
                d["status"] = "BOUNCED"
                touch(d)
    return success(press_release_out(rec))
