"""Campaign CRUD + lifecycle."""
from flask import Blueprint, request

from .. import store
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import (
    get_json_body,
    require_fields,
    require_enum,
    check_version_if_provided,
)
from ..services.paths import resolve_advertiser, resolve_campaign
from ..services.lifecycle import pause_campaign_cascade, end_campaign_cascade


bp = Blueprint("campaigns", __name__)


PACING = ["STANDARD", "ACCELERATED"]


def _check_advertiser_state(adv):
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")


def _validate_budget(daily: int, lifetime):
    if daily < 100:
        raise ApiError("ERR_INVALID_BUDGET", "daily_budget_cents must be >= 100.")
    if lifetime is not None and int(lifetime) < daily:
        raise ApiError("ERR_INVALID_BUDGET", "lifetime_budget_cents must be >= daily_budget_cents.")


def _validate_dates(start_date, end_date):
    if end_date is None:
        return
    if start_date > end_date:
        raise ApiError("ERR_INVALID_CAMPAIGN_DATES")


@bp.post("/advertisers/<advertiser_id>/campaigns")
@require_auth(["CampaignManager", "AccountOwner"])
def create_campaign(advertiser_id):
    adv = resolve_advertiser(advertiser_id)
    _check_advertiser_state(adv)

    body = get_json_body()
    require_fields(body, ["name", "daily_budget_cents", "pacing_strategy", "start_date"])
    require_enum(body, "pacing_strategy", PACING)

    daily = int(body["daily_budget_cents"])
    lifetime = body.get("lifetime_budget_cents")
    _validate_budget(daily, lifetime)
    _validate_dates(body["start_date"], body.get("end_date"))

    rec = {
        "id": store.gen_uuid(),
        "advertiser_id": advertiser_id,
        "name": body["name"],
        "daily_budget_cents": daily,
        "lifetime_budget_cents": int(lifetime) if lifetime is not None else None,
        "pacing_strategy": body["pacing_strategy"],
        "status": "DRAFT",
        "start_date": body["start_date"],
        "end_date": body.get("end_date"),
        "lifetime_spent_cents": 0,
        "today_spent_cents": 0,
        "created_seq": store.next_campaign_seq(advertiser_id),
    }
    store.stamp_common(rec, with_version=True)
    store.insert("Campaign", rec)
    return success(rec, status=201)


@bp.get("/advertisers/<advertiser_id>/campaigns")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager", "FinanceOfficer"])
def list_campaigns(advertiser_id):
    resolve_advertiser(advertiser_id)
    limit, offset = get_pagination()
    rows = [c for c in store.list_all("Campaign") if c.get("advertiser_id") == advertiser_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


@bp.put("/advertisers/<advertiser_id>/campaigns/<campaign_id>")
@require_auth(["CampaignManager", "AccountOwner"])
def update_campaign(advertiser_id, campaign_id):
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    _check_advertiser_state(adv)
    body = get_json_body()
    check_version_if_provided(body, camp)

    new_daily = int(body["daily_budget_cents"]) if body.get("daily_budget_cents") is not None else camp["daily_budget_cents"]
    new_lifetime = (
        int(body["lifetime_budget_cents"])
        if body.get("lifetime_budget_cents") is not None
        else camp.get("lifetime_budget_cents")
    )
    _validate_budget(new_daily, new_lifetime)
    new_end = body["end_date"] if "end_date" in body else camp.get("end_date")
    _validate_dates(camp.get("start_date"), new_end)

    if "name" in body and body["name"] is not None:
        camp["name"] = body["name"]
    camp["daily_budget_cents"] = new_daily
    camp["lifetime_budget_cents"] = new_lifetime
    if "pacing_strategy" in body and body["pacing_strategy"] is not None:
        require_enum(body, "pacing_strategy", PACING)
        camp["pacing_strategy"] = body["pacing_strategy"]
    if "end_date" in body:
        camp["end_date"] = body["end_date"]
    store.touch(camp)

    # If new daily budget is less than today's spend, immediately exhaust.
    if int(camp.get("today_spent_cents", 0)) >= int(camp["daily_budget_cents"]):
        if camp.get("status") in ("ACTIVE", "PAUSED"):
            camp["status"] = "BUDGET_EXHAUSTED"
            store.touch(camp)
            for ag in store.list_all("AdGroup"):
                if ag.get("campaign_id") == camp["id"] and ag.get("status") == "RUNNING":
                    ag["status"] = "BUDGET_EXHAUSTED"
                    store.touch(ag)

    return success(camp)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/activate")
@require_auth(["CampaignManager", "AccountOwner"])
def activate_campaign(advertiser_id, campaign_id):
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if adv.get("status") != "ACTIVE":
        raise ApiError("ERR_ADVERTISER_NOT_ACTIVE")

    status = camp.get("status")
    if status not in ("DRAFT", "PAUSED"):
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    # At least one ad-group with approved_creative_count >= 1
    has_eligible_ag = any(
        ag.get("campaign_id") == campaign_id and int(ag.get("approved_creative_count", 0)) >= 1
        for ag in store.list_all("AdGroup")
    )
    if not has_eligible_ag:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE", "Campaign needs at least one ad-group with approved creatives.")

    if status == "PAUSED":
        if adv.get("balance_state") == "ZERO_BALANCE":
            raise ApiError("ERR_ZERO_BALANCE")
    else:  # DRAFT
        # From DRAFT, do not block on ZERO_BALANCE per scaffold preconditions only require advertiser.status=ACTIVE
        pass

    camp["status"] = "ACTIVE"
    store.touch(camp)
    return success(camp)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/pause")
@require_auth(["CampaignManager", "AccountOwner"])
def pause_campaign(advertiser_id, campaign_id):
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    if adv.get("status") == "SUSPENDED":
        raise ApiError("ERR_ADVERTISER_SUSPENDED")
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")

    if camp.get("status") not in ("ACTIVE", "BUDGET_EXHAUSTED"):
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    pause_campaign_cascade(camp, cascade=True)
    return success(camp)


@bp.post("/advertisers/<advertiser_id>/campaigns/<campaign_id>/end")
@require_auth(["CampaignManager", "AccountOwner"])
def end_campaign(advertiser_id, campaign_id):
    adv, camp = resolve_campaign(advertiser_id, campaign_id)
    if adv.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if camp.get("status") == "ENDED":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    end_campaign_cascade(camp)
    return success(camp)
