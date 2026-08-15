"""Marketing beats and promo campaigns."""

from flask import Blueprint

from db import db
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, parse_date, days_later, v_int, v_num, v_enum, v_date,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import recompute_account_totals
from services.domain import account_of_contract, artist_of_contract

bp = Blueprint("marketing", __name__)

BEAT_TYPES = ["TEASER", "SINGLE_DROP", "VIDEO", "PRESS", "TOUR_ANNOUNCE"]
BEAT_CHANNELS = ["PLAYLIST", "RADIO", "SOCIAL", "PRESS"]
CAMPAIGN_CHANNELS = ["PLAYLIST", "RADIO"]
BEAT_ACTIVE_STATES = ("PLANNED", "READY", "EXECUTED", "MEASURED")
CAMPAIGN_ACTIVATABLE_DIST = ("SCHEDULED", "DELIVERED", "LIVE")


def _label_of_release(release):
    contract = db.contracts.get(release["contract_id"])
    artist = artist_of_contract(contract) if contract else None
    return db.labels.get(artist["label_id"]) if artist else None


def _artist_of_release(release):
    contract = db.contracts.get(release["contract_id"])
    return artist_of_contract(contract) if contract else None


# ---------------------------------------------------------------------------
# Marketing beats
# ---------------------------------------------------------------------------

@bp.post("/api/releases/<rid>/beats")
def create_beat(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    body = get_body()
    beat_type = v_enum(body, "beat_type", BEAT_TYPES)
    channel = v_enum(body, "channel", BEAT_CHANNELS)
    start_date = v_date(body, "start_date")
    end_date = v_date(body, "end_date")
    budget = v_int(body, "budget_cents", min_v=0)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end <= start:
        raise_err("ERR_INVALID_REQUEST", "end_date must be after start_date")

    label = _label_of_release(release)
    rel_date = release["_release_date"]
    window_start = days_later(rel_date, -label["beat_pre_release_days"])
    window_end = days_later(rel_date, label["beat_post_release_days"])
    if start < window_start or end > window_end:
        raise_err("ERR_BEAT_OUTSIDE_WINDOW", "Beat is outside the release beat window")
    for other in db.beats.values():
        if (other["release_id"] == rid and other["channel"] == channel
                and other["status"] in BEAT_ACTIVE_STATES):
            o_start = other["_start_date"]
            o_end = other["_end_date"]
            if start < o_end and o_start < end:
                raise_err("ERR_BEAT_WINDOW_OVERLAP",
                          "Beat overlaps another beat on the same release and channel")
    beat = make_entity({
        "release_id": rid,
        "beat_type": beat_type,
        "channel": channel,
        "start_date": start_date,
        "end_date": end_date,
        "budget_cents": budget,
        "impressions": None,
        "engagement_score": None,
        "status": "PLANNED",
        "_start_date": start,
        "_end_date": end,
    })
    db.beats[beat["id"]] = beat
    return ok(serialize(beat), code=201)


@bp.get("/api/beats/<bid>")
def get_beat(bid):
    auth(["LabelAdmin", "AnRManager", "MarketingManager"])
    beat = get_or_404(db.beats, bid)
    return ok(serialize(beat))


@bp.get("/api/releases/<rid>/beats")
def list_release_beats(rid):
    uid, role = auth(["LabelAdmin", "AnRManager", "MarketingManager", "ArtistPortal"])
    release = get_or_404(db.releases, rid)
    artist = _artist_of_release(release)
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [b for b in db.beats.values() if b["release_id"] == rid]
    items = apply_filters(items, [
        ("status", lambda b: b["status"]),
        ("channel", lambda b: b["channel"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/beats/<bid>/ready")
def ready_beat(bid):
    auth(["MarketingManager"])
    beat = get_or_404(db.beats, bid)
    get_body()
    if beat["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE", "Only a PLANNED beat may be readied")
    beat["status"] = "READY"
    touch(beat)
    return ok(serialize(beat))


@bp.post("/api/beats/<bid>/execute")
def execute_beat(bid):
    auth(["MarketingManager"])
    beat = get_or_404(db.beats, bid)
    get_body()
    if beat["status"] != "READY":
        raise_err("ERR_INVALID_STATE", "Only a READY beat may be executed")
    beat["status"] = "EXECUTED"
    touch(beat)
    return ok(serialize(beat))


@bp.post("/api/beats/<bid>/measure")
def measure_beat(bid):
    auth(["MarketingManager"])
    beat = get_or_404(db.beats, bid)
    body = get_body()
    impressions = v_int(body, "impressions", min_v=0)
    engagement_score = v_num(body, "engagement_score")
    if beat["status"] != "EXECUTED":
        raise_err("ERR_INVALID_STATE", "Only an EXECUTED beat may be measured")
    beat["impressions"] = impressions
    beat["engagement_score"] = engagement_score
    beat["status"] = "MEASURED"
    touch(beat)
    return ok(serialize(beat))


@bp.post("/api/beats/<bid>/skip")
def skip_beat(bid):
    auth(["MarketingManager"])
    beat = get_or_404(db.beats, bid)
    get_body()
    if beat["status"] not in ("PLANNED", "READY"):
        raise_err("ERR_INVALID_STATE", "Beat in %s cannot be skipped" % beat["status"])
    beat["status"] = "SKIPPED"
    touch(beat)
    return ok(serialize(beat))


# ---------------------------------------------------------------------------
# Promo campaigns
# ---------------------------------------------------------------------------

@bp.post("/api/releases/<rid>/promo-campaigns")
def create_campaign(rid):
    auth(["MarketingManager"])
    release = get_or_404(db.releases, rid)
    body = get_body()
    channel = v_enum(body, "channel", CAMPAIGN_CHANNELS)
    start_date = v_date(body, "start_date")
    end_date = v_date(body, "end_date")
    spend_cap = v_int(body, "spend_cap_cents", min_v=1)
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        raise_err("ERR_INVALID_REQUEST", "end_date must be on or after start_date")

    label = _label_of_release(release)
    gap = label["campaign_gap_days"]
    for other in db.campaigns.values():
        if (other["release_id"] == rid and other["channel"] == channel
                and other["status"] != "KILLED"):
            o_start = other["_start_date"]
            o_end = other["_end_date"]
            separated = (days_later(end, gap) <= o_start) or (days_later(o_end, gap) <= start)
            if not separated:
                raise_err("ERR_CAMPAIGN_WINDOW_CONFLICT",
                          "Campaign conflicts with another campaign on the same release and channel")
    campaign = make_entity({
        "release_id": rid,
        "channel": channel,
        "start_date": start_date,
        "end_date": end_date,
        "spend_cap_cents": spend_cap,
        "spend_cents": 0,
        "status": "DRAFT",
        "_start_date": start,
        "_end_date": end,
    })
    db.campaigns[campaign["id"]] = campaign
    return ok(serialize(campaign), code=201)


@bp.get("/api/promo-campaigns/<cid>")
def get_campaign(cid):
    auth(["LabelAdmin", "AnRManager", "MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    return ok(serialize(campaign))


@bp.get("/api/releases/<rid>/promo-campaigns")
def list_release_campaigns(rid):
    uid, role = auth(["LabelAdmin", "AnRManager", "MarketingManager", "ArtistPortal"])
    release = get_or_404(db.releases, rid)
    artist = _artist_of_release(release)
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [c for c in db.campaigns.values() if c["release_id"] == rid]
    items = apply_filters(items, [
        ("status", lambda c: c["status"]),
        ("channel", lambda c: c["channel"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


def _campaign_release(campaign):
    return db.releases.get(campaign["release_id"])


@bp.post("/api/promo-campaigns/<cid>/activate")
def activate_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    get_body()
    if campaign["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Only a DRAFT campaign may be activated")
    release = _campaign_release(campaign)
    if release["distribution_status"] not in CAMPAIGN_ACTIVATABLE_DIST:
        raise_err("ERR_INVALID_STATE", "Release must be SCHEDULED, DELIVERED, or LIVE")
    campaign["status"] = "ACTIVE"
    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/api/promo-campaigns/<cid>/pause")
def pause_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    get_body()
    if campaign["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Only an ACTIVE campaign may be paused")
    campaign["status"] = "PAUSED"
    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/api/promo-campaigns/<cid>/resume")
def resume_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    get_body()
    if campaign["status"] != "PAUSED":
        raise_err("ERR_INVALID_STATE", "Only a PAUSED campaign may be resumed")
    release = _campaign_release(campaign)
    if release["distribution_status"] not in CAMPAIGN_ACTIVATABLE_DIST:
        raise_err("ERR_INVALID_STATE", "Release must be SCHEDULED, DELIVERED, or LIVE")
    campaign["status"] = "ACTIVE"
    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/api/promo-campaigns/<cid>/complete")
def complete_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    get_body()
    if campaign["status"] not in ("ACTIVE", "PAUSED"):
        raise_err("ERR_INVALID_STATE", "Campaign in %s cannot be completed" % campaign["status"])
    campaign["status"] = "COMPLETED"
    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/api/promo-campaigns/<cid>/kill")
def kill_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    get_body()
    if campaign["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise_err("ERR_INVALID_STATE", "Campaign in %s cannot be killed" % campaign["status"])
    campaign["status"] = "KILLED"
    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/api/promo-campaigns/<cid>/spend")
def spend_campaign(cid):
    auth(["MarketingManager"])
    campaign = get_or_404(db.campaigns, cid)
    body = get_body()
    amount = v_int(body, "amount_cents", min_v=1)
    if campaign["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Spend may only be recorded on an ACTIVE campaign")
    if campaign["spend_cents"] + amount > campaign["spend_cap_cents"]:
        raise_err("ERR_CAMPAIGN_CAP_EXCEEDED", "Spend would exceed the campaign cap")
    campaign["spend_cents"] += amount
    touch(campaign)
    release = _campaign_release(campaign)
    contract = db.contracts.get(release["contract_id"])
    if contract["promo_costs_recoupable"]:
        account = account_of_contract(contract["id"])
        if account is not None:
            account["promo_balance_cents"] += amount
            recompute_account_totals(account)
            touch(account)
    return ok(serialize(campaign))
