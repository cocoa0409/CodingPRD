"""AdCampaign & AdSlot endpoints — sponsorship (PRD §3.10, §2.11)."""
from flask import Blueprint, request

import errors
import middleware as mw
from constants import AD_PLACEMENTS, PLATFORM_FEE_DEFAULT, PLATFORM_FEE_MAX, PLATFORM_FEE_MIN
from db import db
from response import array_response, object_response
from routes.common import get_or_404
from serialize import serialize, serialize_list
from services import calc

bp = Blueprint("ad_campaigns", __name__)


# ---- AdCampaign ----
@bp.post("/ad-campaigns")
def create_campaign():
    auth = mw.authenticate()
    mw.require_role(auth, {"AdOps"})
    body = mw.get_json_body()
    show_id = mw.require_string(body, "show_id")
    get_or_404(db.shows, show_id)
    sponsor_name = mw.require_string(body, "sponsor_name")
    platform_fee = mw.optional_number(body, "platform_fee_pct", PLATFORM_FEE_DEFAULT)
    if platform_fee < PLATFORM_FEE_MIN or platform_fee > PLATFORM_FEE_MAX:
        raise errors.err(errors.ERR_INVALID_REQUEST, "platform_fee_pct out of range")
    rec = db.ad_campaigns.create({
        "show_id": show_id,
        "sponsor_name": sponsor_name,
        "platform_fee_pct": platform_fee,
        "show_payout_cents": 0,
        "platform_take_cents": 0,
        "status": "DRAFT",
    })
    return object_response(serialize(rec), status=201)


@bp.get("/ad-campaigns")
def list_campaigns():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "AdOps"})
    limit, offset = mw.parse_pagination()
    records = db.ad_campaigns.all()
    show_id = request.args.get("show_id")
    status = request.args.get("status")
    if show_id is not None:
        records = [r for r in records if r["show_id"] == show_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/ad-campaigns/<rid>")
def get_campaign(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "AdOps"})
    rec = get_or_404(db.ad_campaigns, rid)
    return object_response(serialize(rec))


@bp.post("/ad-campaigns/<rid>/approve")
def approve_campaign(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"AdOps"})
    rec = get_or_404(db.ad_campaigns, rid)
    if rec["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Campaign is not DRAFT")
    slot_count = sum(1 for s in db.ad_slots.all() if s["campaign_id"] == rec["id"])
    if slot_count < 1:
        raise errors.err(errors.ERR_NO_SLOTS, "Campaign has no slots")
    rec["status"] = "APPROVED"
    db.ad_campaigns.touch(rec)
    return object_response(serialize(rec))


@bp.post("/ad-campaigns/<rid>/reconcile")
def reconcile_campaign(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"AdOps"})
    rec = get_or_404(db.ad_campaigns, rid)
    body = mw.get_json_body()
    # state legality first (PRD §2.8), then OCC, then slot-published business rule
    if rec["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Campaign is not APPROVED")
    expected = body.get("expected_adcampaign_version")
    if expected is None:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Missing required field: expected_adcampaign_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "expected_adcampaign_version must be an integer")
    if expected != rec["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Campaign version is stale")
    slots = [s for s in db.ad_slots.all() if s["campaign_id"] == rec["id"]]
    for s in slots:
        ep = db.episodes.get(s["episode_id"])
        if ep is None or ep["status"] != "PUBLISHED":
            raise errors.err(errors.ERR_SLOT_EPISODE_NOT_PUBLISHED,
                             "A slot's episode is not PUBLISHED")
    show_payout, platform_take = calc.ad_revenue_split(slots, rec["platform_fee_pct"])
    rec["show_payout_cents"] = show_payout
    rec["platform_take_cents"] = platform_take
    rec["status"] = "RECONCILED"
    db.ad_campaigns.touch(rec)
    return object_response(serialize(rec))


@bp.post("/ad-campaigns/<rid>/cancel")
def cancel_campaign(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"AdOps"})
    rec = get_or_404(db.ad_campaigns, rid)
    if rec["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Campaign is not DRAFT")
    rec["status"] = "CANCELLED"
    db.ad_campaigns.touch(rec)
    return object_response(serialize(rec))


# ---- AdSlot ----
@bp.post("/ad-slots")
def create_slot():
    auth = mw.authenticate()
    mw.require_role(auth, {"AdOps"})
    body = mw.get_json_body()
    campaign_id = mw.require_string(body, "campaign_id")
    campaign = get_or_404(db.ad_campaigns, campaign_id)
    episode_id = mw.require_string(body, "episode_id")
    get_or_404(db.episodes, episode_id)
    placement = mw.require_enum(body, "placement", AD_PLACEMENTS)
    gross_cents = mw.require_int(body, "gross_cents")
    if gross_cents < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "gross_cents must be >= 1")
    # slot added only to a DRAFT campaign (PRD §3.10)
    if campaign["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Campaign is not DRAFT")
    rec = db.ad_slots.create({
        "campaign_id": campaign_id,
        "episode_id": episode_id,
        "placement": placement,
        "gross_cents": gross_cents,
    })
    # adding a slot changes the slot set -> bump owning campaign version (PRD §3.10)
    db.ad_campaigns.touch(campaign)
    return object_response(serialize(rec), status=201)


@bp.get("/ad-slots")
def list_slots():
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "AdOps"})
    limit, offset = mw.parse_pagination()
    records = db.ad_slots.all()
    campaign_id = request.args.get("campaign_id")
    episode_id = request.args.get("episode_id")
    if campaign_id is not None:
        records = [r for r in records if r["campaign_id"] == campaign_id]
    if episode_id is not None:
        records = [r for r in records if r["episode_id"] == episode_id]
    page, meta = mw.paginate(records, limit, offset)
    return array_response(serialize_list(page), meta)


@bp.get("/ad-slots/<rid>")
def get_slot(rid):
    auth = mw.authenticate()
    mw.require_role(auth, {"PlatformAdmin", "AdOps"})
    rec = get_or_404(db.ad_slots, rid)
    return object_response(serialize(rec))
