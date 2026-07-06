"""Pitch endpoints and lifecycle (PRD 3.4)."""
from flask import Blueprint, request

import db
from clock import clock
from common import (get_json_body, get_or_404, new_record, paginate,
                    parse_pagination, ref_or_404, require_bool, require_str, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import pitch_out

bp = Blueprint("pitches", __name__)

PITCH_STATUSES = {"DRAFT", "SENT", "RESPONDED", "ACCEPTED", "REJECTED", "DECLINED", "CANCELLED"}

# A media list's "open count" considers pitches in these states (PRD 3.4).
_LIST_OPEN_STATES = ("DRAFT", "SENT", "RESPONDED", "ACCEPTED")


@bp.post("/agency/pitches")
@authorize(["MediaSpecialist"])
def create_pitch():
    body = get_json_body()
    campaign_id = body.get("campaign_id")
    media_list_id = body.get("media_list_id")
    journalist_id = body.get("journalist_id")
    # Priority 4: FK existence (left-to-right ordering of body refs).
    ref_or_404(db.campaigns, campaign_id, "campaign_id")
    media_list = ref_or_404(db.media_lists, media_list_id, "media_list_id")
    ref_or_404(db.journalists, journalist_id, "journalist_id")
    # Priority 5: well-formedness.
    angle = require_str(body, "angle")
    is_exclusive = require_bool(body, "is_exclusive", default=False)

    # Priority 8: business referential — journalist must be in the list.
    if journalist_id not in media_list["journalist_ids"]:
        raise err("ERR_JOURNALIST_NOT_IN_LIST",
                  "Pitch journalist is not a member of the media list")

    rec = new_record({
        "campaign_id": campaign_id,
        "media_list_id": media_list_id,
        "journalist_id": journalist_id,
        "angle": angle,
        "is_exclusive": is_exclusive,
        "status": "DRAFT",
        "sent_at": None,
    })
    db.pitches[rec["id"]] = rec
    return success(pitch_out(rec), status=201)


@bp.get("/agency/pitches/<pitch_id>")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def get_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    return success(pitch_out(rec))


@bp.get("/agency/pitches")
@authorize(["AccountManager", "MediaSpecialist", "PlatformAdmin"])
def list_pitches():
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    media_list_id = request.args.get("media_list_id")
    journalist_id = request.args.get("journalist_id")
    status = request.args.get("status")
    if status is not None and status not in PITCH_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.pitches.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if media_list_id is not None and r["media_list_id"] != media_list_id:
            continue
        if journalist_id is not None and r["journalist_id"] != journalist_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([pitch_out(r) for r in page], pagination=meta)


def _maybe_exhaust_list(media_list_id):
    """Bubble-up: if a list's open count reaches exactly 0, ACTIVE -> EXHAUSTED."""
    ml = db.media_lists.get(media_list_id)
    if ml is None or ml["status"] != "ACTIVE":
        return
    open_count = sum(
        1 for p in db.pitches.values()
        if p["media_list_id"] == media_list_id and p["status"] in _LIST_OPEN_STATES)
    if open_count == 0:
        ml["status"] = "EXHAUSTED"
        touch(ml)


@bp.post("/agency/pitches/<pitch_id>/send")
@authorize(["MediaSpecialist"])
def send_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Pitch is not DRAFT")
    campaign = db.campaigns[rec["campaign_id"]]
    journalist = db.journalists[rec["journalist_id"]]
    media_list = db.media_lists[rec["media_list_id"]]
    if campaign["status"] != "ACTIVE":
        raise err("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    if journalist["status"] != "ACTIVE":
        raise err("ERR_JOURNALIST_BLOCKLISTED", "Journalist is blocklisted")
    if media_list["status"] != "ACTIVE":
        raise err("ERR_MEDIA_LIST_NOT_ACTIVE", "Source media list is not ACTIVE")
    rec["status"] = "SENT"
    rec["sent_at"] = clock.now_iso()
    touch(rec)
    return success(pitch_out(rec))


@bp.post("/agency/pitches/<pitch_id>/respond")
@authorize(["MediaSpecialist"])
def respond_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    if rec["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Pitch is not SENT")
    campaign = db.campaigns[rec["campaign_id"]]
    if campaign["status"] != "ACTIVE":
        raise err("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    rec["status"] = "RESPONDED"
    touch(rec)
    return success(pitch_out(rec))


@bp.post("/agency/pitches/<pitch_id>/accept")
@authorize(["MediaSpecialist"])
def accept_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    if rec["status"] != "RESPONDED":
        raise err("ERR_INVALID_STATE", "Pitch is not RESPONDED")
    rec["status"] = "ACCEPTED"
    touch(rec)
    return success(pitch_out(rec))


@bp.post("/agency/pitches/<pitch_id>/reject")
@authorize(["MediaSpecialist"])
def reject_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    if rec["status"] != "RESPONDED":
        raise err("ERR_INVALID_STATE", "Pitch is not RESPONDED")
    rec["status"] = "REJECTED"
    touch(rec)
    _maybe_exhaust_list(rec["media_list_id"])
    return success(pitch_out(rec))


@bp.post("/agency/pitches/<pitch_id>/decline")
@authorize(["MediaSpecialist"])
def decline_pitch(pitch_id):
    rec = get_or_404(db.pitches, pitch_id)
    if rec["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Pitch is not SENT")
    rec["status"] = "DECLINED"
    touch(rec)
    _maybe_exhaust_list(rec["media_list_id"])
    return success(pitch_out(rec))
