"""AdCampaign endpoints, budget ledger, and lifecycle (PRD §3.4)."""

from flask import request

import common
import db
import errors
import lifecycle
import ownership
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body
from timeutil import parse_iso


def register(app):
    @app.route("/ad-campaigns", methods=["POST"])
    def create_campaign():
        caller = auth_and_role(["Advertiser"])
        data = body()
        advertiser_id = common.require_str(data, "advertiser_id")
        name = common.require_str(data, "name")
        budget_cents = common.require_int(data, "budget_cents")
        if budget_cents <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "budget_cents must be > 0")
        bid_cpm_cents = common.require_int(data, "bid_cpm_cents")
        if bid_cpm_cents <= 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "bid_cpm_cents must be > 0")
        targeting_category = common.require_enum(data, "targeting_category", db.CATEGORIES)
        premium = common.optional_bool(data, "premium_targeting", False)
        flight_start = common.require_str(data, "flight_start")
        flight_end = common.require_str(data, "flight_end")
        try:
            parse_iso(flight_start)
            parse_iso(flight_end)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "flight_start/flight_end must be ISO 8601 timestamps")
        # Ownership: Advertiser creates only under their own id.
        if advertiser_id != caller.user_id:
            raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Advertiser may only create campaigns under their own id")
        ownership.get_advertiser(advertiser_id)
        rec = new_common()
        rec.update({
            "advertiser_id": advertiser_id,
            "name": name,
            "budget_cents": budget_cents,
            "bid_cpm_cents": bid_cpm_cents,
            "targeting_category": targeting_category,
            "premium_targeting": premium,
            "flight_start": flight_start,
            "flight_end": flight_end,
            "status": "DRAFT",
            "reserved_budget_cents": 0,
            "spent_budget_cents": 0,
            "available_budget_cents": budget_cents,
        })
        db.db.ad_campaigns[rec["id"]] = rec
        return success(serialize.ad_campaign(rec), status=201)

    @app.route("/ad-campaigns", methods=["GET"])
    def list_campaigns():
        auth_and_role(["PlatformAdmin", "Advertiser"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.ad_campaigns.values())
        advertiser_id = request.args.get("advertiser_id")
        if advertiser_id:
            items = [c for c in items if c["advertiser_id"] == advertiser_id]
        status = request.args.get("status")
        if status:
            items = [c for c in items if c["status"] == status]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.ad_campaign(c) for c in page], limit, offset, total)

    @app.route("/ad-campaigns/<cid>", methods=["GET"])
    def get_campaign(cid):
        auth_and_role(["PlatformAdmin", "Advertiser"])
        c = ownership.get_campaign(cid)
        return success(serialize.ad_campaign(c), status=200)

    @app.route("/ad-campaigns/<cid>/activate", methods=["POST"])
    def activate_campaign(cid):
        caller = auth_and_role(["Advertiser"])
        c = ownership.get_campaign(cid)
        ownership.assert_advertiser_owns_campaign(caller, c)
        # State: DRAFT/PAUSED -> ACTIVE (EXHAUSTED can never reactivate).
        if c["status"] == "DRAFT":
            # budget_cents > 0 is guaranteed at creation.
            pass
        elif c["status"] == "PAUSED":
            # PAUSED -> ACTIVE requires available_budget_cents > 0.
            if c["available_budget_cents"] <= 0:
                raise errors.err(errors.ERR_INVALID_STATE, "Campaign has no available budget to reactivate")
        else:
            raise errors.err(errors.ERR_INVALID_STATE, "Campaign cannot be activated from its current state")
        c["status"] = "ACTIVE"
        touch(c)
        return success(serialize.ad_campaign(c), status=200)

    @app.route("/ad-campaigns/<cid>/pause", methods=["POST"])
    def pause_campaign(cid):
        caller = auth_and_role(["Advertiser"])
        c = ownership.get_campaign(cid)
        ownership.assert_advertiser_owns_campaign(caller, c)
        if c["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE campaign may be paused")
        c["status"] = "PAUSED"
        touch(c)
        # Cascade L1: PROPOSED placements -> REJECTED, reserves released.
        lifecycle.reject_proposed_placements(c)
        return success(serialize.ad_campaign(c), status=200)

    @app.route("/ad-campaigns/<cid>/complete", methods=["POST"])
    def complete_campaign(cid):
        caller = auth_and_role(["Advertiser"])
        c = ownership.get_campaign(cid)
        ownership.assert_advertiser_owns_campaign(caller, c)
        if c["status"] not in ("ACTIVE", "EXHAUSTED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Campaign cannot be completed from its current state")
        # No open placements (PROPOSED/INSERTED) allowed.
        for p in db.db.ad_placements.values():
            if p["campaign_id"] == c["id"] and p["status"] in ("PROPOSED", "INSERTED"):
                raise errors.err(errors.ERR_CAMPAIGN_HAS_OPEN_PLACEMENTS,
                                 "Campaign still has open placements")
        c["status"] = "COMPLETED"
        touch(c)
        return success(serialize.ad_campaign(c), status=200)
