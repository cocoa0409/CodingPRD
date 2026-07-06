"""AdSpendDispute routes."""
from flask import Blueprint, request

import services
from auth import require_auth, require_role
from db import store, base_record, touch
from errors import err
from helpers import (
    get_body, require_str, require_int, require_enum, find, assert_owns_client,
    paginate, parse_pagination,
)
from response import ok_object, ok_list

bp = Blueprint("disputes", __name__)


@bp.route("/ad-spend-disputes", methods=["POST"])
def open_dispute():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    body = get_body()
    ad_campaign_id = require_str(body, "ad_campaign_id")
    client_id = require_str(body, "client_id")
    campaign = find("ad_campaign", ad_campaign_id)
    client = find("client", client_id)
    disputed_cents = require_int(body, "disputed_cents", minimum=1)

    # Client actor may only open disputes for its own client.
    assert_owns_client(principal, client)

    rec = base_record(versioned=True)
    rec.update({
        "ad_campaign_id": ad_campaign_id,
        "client_id": client_id,
        "disputed_cents": disputed_cents,
        "credited_cents": 0,
        "status": "OPEN",
    })
    store.ad_spend_disputes[rec["id"]] = rec

    services.recompute_open_dispute_count(client)
    touch(client)
    return ok_object(rec, 201)


@bp.route("/ad-spend-disputes/<did>", methods=["GET"])
def get_dispute(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    disp = find("ad_spend_dispute", did)
    client = find("client", disp["client_id"])
    assert_owns_client(principal, client)
    return ok_object(disp, 200)


@bp.route("/ad-spend-disputes", methods=["GET"])
def list_disputes():
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager", "Client"])
    parse_pagination()
    campaign_filter = request.args.get("ad_campaign_id")
    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")
    records = list(store.ad_spend_disputes.values())
    if principal.role == "Client":
        records = [d for d in records if d["client_id"] == principal.user_id]
    if campaign_filter is not None:
        records = [d for d in records if d["ad_campaign_id"] == campaign_filter]
    if client_filter is not None:
        records = [d for d in records if d["client_id"] == client_filter]
    if status_filter is not None:
        records = [d for d in records if d["status"] == status_filter]
    page, limit, offset, total = paginate(records)
    return ok_list(page, limit, offset, total)


@bp.route("/ad-spend-disputes/<did>/review", methods=["POST"])
def review_dispute(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    disp = find("ad_spend_dispute", did)
    if disp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Dispute must be OPEN to review")
    disp["status"] = "UNDER_REVIEW"
    touch(disp)
    return ok_object(disp, 200)


@bp.route("/ad-spend-disputes/<did>/resolve", methods=["POST"])
def resolve_dispute(did):
    principal = require_auth()
    require_role(principal, ["AgencyAdmin", "AccountManager"])
    disp = find("ad_spend_dispute", did)
    body = get_body()
    outcome = require_enum(body, "outcome", {"UPHELD", "DENIED"})

    if disp["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Dispute must be UNDER_REVIEW to resolve")

    campaign = find("ad_campaign", disp["ad_campaign_id"])
    client = find("client", disp["client_id"])

    if outcome == "UPHELD":
        if disp["disputed_cents"] > campaign["spent_cents"]:
            raise err("ERR_DISPUTE_EXCEEDS_SPEND", "Credit would exceed campaign spend")
        disp["credited_cents"] = disp["disputed_cents"]
        campaign["spent_cents"] -= disp["disputed_cents"]
        # recompute fee only while UNBILLED; an INVOICED fee is frozen
        if campaign["billing_status"] == "UNBILLED":
            services.recompute_campaign_fee(campaign)
        disp["status"] = "UPHELD"
        touch(campaign)
    else:
        disp["status"] = "DENIED"
        # credited_cents stays 0

    touch(disp)
    services.recompute_open_dispute_count(client)
    services.recompute_health_score(client)
    touch(client)
    return ok_object(disp, 200)


@bp.route("/ad-spend-disputes/<did>/withdraw", methods=["POST"])
def withdraw_dispute(did):
    principal = require_auth()
    require_role(principal, ["Client"])
    disp = find("ad_spend_dispute", did)
    client = find("client", disp["client_id"])
    assert_owns_client(principal, client)
    if disp["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise err("ERR_INVALID_STATE", "Dispute must be OPEN or UNDER_REVIEW to withdraw")
    disp["status"] = "WITHDRAWN"
    touch(disp)
    services.recompute_open_dispute_count(client)
    services.recompute_health_score(client)
    touch(client)
    return ok_object(disp, 200)
