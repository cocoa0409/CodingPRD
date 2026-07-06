"""AdCampaign routes: two independent state dimensions + spend & fee."""
from flask import Blueprint, request

import calc
import services
from auth import require_auth, require_role
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_enum, require_int, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("campaigns", __name__)

CHANNELS = {"GOOGLE_ADS", "META", "BING"}


@bp.route("/ad-campaigns", methods=["POST"])
def create_campaign():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    body = get_body()
    client_id = require_str(body, "client_id")
    retainer_id = require_str(body, "retainer_id")
    client = find("client", client_id)
    retainer = find("retainer", retainer_id)
    channel = require_enum(body, "channel", CHANNELS)
    budget_cents = require_int(body, "budget_cents", minimum=0)

    rec = base_record(versioned=True)
    rec.update({
        "client_id": client_id,
        "retainer_id": retainer_id,
        "channel": channel,
        "budget_cents": budget_cents,
        "spent_cents": 0,
        "management_fee_cents": 0,
        "lifecycle_status": "DRAFT",
        "billing_status": "UNBILLED",
    })
    store.ad_campaigns[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/ad-campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    camp = find("ad_campaign", cid)
    client = find("client", camp["client_id"])
    assert_owns_client(principal, client)
    # recompute live fee while UNBILLED
    if camp["billing_status"] == "UNBILLED":
        services.recompute_campaign_fee(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns", methods=["GET"])
def list_campaigns():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Reseller", "Client"])
    parse_pagination()
    client_filter = request.args.get("client_id")
    retainer_filter = request.args.get("retainer_id")
    lifecycle_filter = request.args.get("lifecycle_status")
    billing_filter = request.args.get("billing_status")
    records = list(store.ad_campaigns.values())
    if principal.role == "Client":
        records = [c for c in records if c["client_id"] == principal.user_id]
    elif principal.role == "Reseller":
        records = [c for c in records
                   if (cl := store.clients.get(c["client_id"])) is not None
                   and cl.get("reseller_id") == principal.user_id]
    if client_filter is not None:
        records = [c for c in records if c["client_id"] == client_filter]
    if retainer_filter is not None:
        records = [c for c in records if c["retainer_id"] == retainer_filter]
    if lifecycle_filter is not None:
        records = [c for c in records if c["lifecycle_status"] == lifecycle_filter]
    if billing_filter is not None:
        records = [c for c in records if c["billing_status"] == billing_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/ad-campaigns/<cid>/launch", methods=["POST"])
def launch_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    if camp["lifecycle_status"] not in ("DRAFT", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Campaign must be DRAFT or PAUSED to launch")
    if camp["lifecycle_status"] == "DRAFT":
        retainer = find("retainer", camp["retainer_id"])
        if retainer["status"] != "ACTIVE":
            raise err("ERR_RETAINER_NOT_ACTIVE", "Linked retainer must be ACTIVE")
    camp["lifecycle_status"] = "LIVE"
    touch(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns/<cid>/pause", methods=["POST"])
def pause_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    if camp["lifecycle_status"] != "LIVE":
        raise err("ERR_INVALID_STATE", "Campaign must be LIVE to pause")
    camp["lifecycle_status"] = "PAUSED"
    touch(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns/<cid>/end", methods=["POST"])
def end_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    if camp["lifecycle_status"] not in ("DRAFT", "LIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Campaign must be DRAFT/LIVE/PAUSED to end")
    camp["lifecycle_status"] = "ENDED"
    touch(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns/<cid>/record-spend", methods=["POST"])
def record_spend(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    body = get_body()
    amount_cents = require_int(body, "amount_cents", minimum=0)
    if camp["spent_cents"] + amount_cents > camp["budget_cents"]:
        raise err("ERR_BUDGET_EXCEEDED", "Recorded spend would exceed budget")
    camp["spent_cents"] += amount_cents
    # recompute live estimate
    services.recompute_campaign_fee(camp)
    touch(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns/<cid>/invoice", methods=["POST"])
def invoice_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    if camp["billing_status"] != "UNBILLED":
        raise err("ERR_INVALID_STATE", "Campaign must be UNBILLED to invoice")
    # no OPEN/UNDER_REVIEW dispute on this campaign
    for disp in store.ad_spend_disputes.values():
        if disp["ad_campaign_id"] == cid and disp["status"] in ("OPEN", "UNDER_REVIEW"):
            raise err("ERR_CAMPAIGN_HAS_OPEN_DISPUTE", "Campaign has an open dispute")
    # freeze fee over current post-dispute spent_cents
    services.recompute_campaign_fee(camp)
    camp["billing_status"] = "INVOICED"
    touch(camp)
    return ok_object(camp, 200)


@bp.route("/ad-campaigns/<cid>/settle", methods=["POST"])
def settle_campaign(cid):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    camp = find("ad_campaign", cid)
    if camp["billing_status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "Campaign must be INVOICED to settle")
    camp["billing_status"] = "SETTLED"
    touch(camp)
    return ok_object(camp, 200)
