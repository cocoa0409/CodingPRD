"""AdGroup CRUD + lifecycle."""
from flask import Blueprint, request

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_enum, check_version_if_provided
from ..services.paths import resolve_campaign, resolve_ad_group
from ..services.lifecycle import archive_ad_group_cascade, pause_ad_group_cascade


bp = Blueprint("ad_groups", __name__)


BIDDING = ["CPC", "CPM", "CPA", "OCPX"]


def _check_advertiser_state(adv):
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")


def _validate_freq_cap(value):
    if value is None:
        return
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError("ERR_INVALID_FREQUENCY_CAP")
    if int(value) < 1:
        raise ApiError("ERR_INVALID_FREQUENCY_CAP")


def _validate_audience(audience_id):
    if audience_id is None:
        return
    # There is no audience-creation endpoint defined in the API surface, so this check
    # validates the *shape* of the reference: a valid audience id is a non-empty string
    # beginning with the "aud_" prefix (the established taxonomy prefix). Strings that
    # don't match are rejected as unknown audiences.
    if not isinstance(audience_id, str) or not audience_id.startswith("aud_"):
        raise ApiError("ERR_AUDIENCE_NOT_FOUND")


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups")
@require_auth(["CampaignManager", "AccountOwner"])
def create_ad_group(advertiser_id, campaign_id):
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    _check_advertiser_state(adv)

    body = get_json_body()
    require_fields(body, ["name", "bidding_strategy", "bid_cents", "targeting_geo"])
    require_enum(body, "bidding_strategy", BIDDING)
    cap = body.get("frequency_cap_per_user_per_day")
    _validate_freq_cap(cap)
    _validate_audience(body.get("remarketing_audience_id"))

    rec = {
        "id": store.gen_uuid(),
        "campaign_id": campaign_id,
        "advertiser_id": advertiser_id,
        "name": body["name"],
        "bidding_strategy": body["bidding_strategy"],
        "bid_cents": int(body["bid_cents"]),
        "targeting_geo": list(body.get("targeting_geo") or []),
        "targeting_demographic": body.get("targeting_demographic"),
        "targeting_interest": list(body.get("targeting_interest") or []),
        "targeting_behavior": list(body.get("targeting_behavior") or []),
        "targeting_device": list(body.get("targeting_device") or []),
        "targeting_dayparts": list(body.get("targeting_dayparts") or []),
        "remarketing_audience_id": body.get("remarketing_audience_id"),
        "frequency_cap_per_user_per_day": int(cap) if cap is not None else None,
        "status": "DRAFT",
        "quality_score": 5.0,
        "predicted_ctr": 0.02,
        "approved_creative_count": 0,
    }
    store.stamp_common(rec, with_version=True)
    store.insert("AdGroup", rec)
    return success(rec, status=201)


@bp.get("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager"])
def list_ad_groups(advertiser_id, campaign_id):
    resolve_campaign(advertiser_id, campaign_id)
    limit, offset = get_pagination()
    rows = [a for a in store.list_all("AdGroup") if a.get("campaign_id") == campaign_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


@bp.put("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>")
@require_auth(["CampaignManager", "AccountOwner"])
def update_ad_group(advertiser_id, campaign_id, ad_group_id):
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    _check_advertiser_state(adv)
    body = get_json_body()
    check_version_if_provided(body, ag)

    if "frequency_cap_per_user_per_day" in body:
        _validate_freq_cap(body["frequency_cap_per_user_per_day"])
        ag["frequency_cap_per_user_per_day"] = body["frequency_cap_per_user_per_day"]
    if "remarketing_audience_id" in body:
        _validate_audience(body["remarketing_audience_id"])
        ag["remarketing_audience_id"] = body["remarketing_audience_id"]

    for fld in (
        "name",
        "bid_cents",
        "targeting_geo",
        "targeting_demographic",
        "targeting_interest",
        "targeting_behavior",
        "targeting_device",
        "targeting_dayparts",
        "quality_score",
        "predicted_ctr",
    ):
        if fld in body and body[fld] is not None:
            ag[fld] = body[fld]
    store.touch(ag)
    return success(ag)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>/activate")
@require_auth(["CampaignManager", "AccountOwner"])
def activate_ad_group(advertiser_id, campaign_id, ad_group_id):
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if adv.get("status") != "ACTIVE":
        raise ApiError("ERR_ADVERTISER_NOT_ACTIVE")
    if camp.get("status") != "ACTIVE":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")
    if ag.get("status") not in ("READY", "PAUSED"):
        raise ApiError("ERR_INVALID_AD_GROUP_STATE")
    if int(ag.get("approved_creative_count", 0)) < 1:
        raise ApiError("ERR_INVALID_AD_GROUP_STATE")
    if adv.get("balance_state") == "ZERO_BALANCE":
        raise ApiError("ERR_ZERO_BALANCE")
    ag["status"] = "RUNNING"
    store.touch(ag)
    return success(ag)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>/pause")
@require_auth(["CampaignManager", "AccountOwner"])
def pause_ad_group(advertiser_id, campaign_id, ad_group_id):
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if ag.get("status") not in ("RUNNING", "BUDGET_EXHAUSTED"):
        raise ApiError("ERR_INVALID_AD_GROUP_STATE")
    ag["status"] = "PAUSED"
    store.touch(ag)
    return success(ag)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/ad-groups/<ad_group_id>/archive")
@require_auth(["CampaignManager", "AccountOwner"])
def archive_ad_group(advertiser_id, campaign_id, ad_group_id):
    adv, camp, ag = resolve_ad_group(advertiser_id, campaign_id, ad_group_id)
    if ag.get("status") == "ARCHIVED":
        raise ApiError("ERR_INVALID_AD_GROUP_STATE")
    archive_ad_group_cascade(ag)
    return success(ag)
