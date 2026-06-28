"""Pledge routes: create (posture-gated), get, list, and the cyclic lifecycle
record / revise / collect / cancel.
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int, opt_int,
                     paginate_and_respond)
from lookups import get_pledge, get_campaign, get_seller
from services import validation, calc
from services.mutations import touch

bp = Blueprint("pledges", __name__)


@bp.route("/fundraising/pledges", methods=["POST"])
@require_roles("CampaignAdmin", "Seller")
def create_pledge():
    body = get_body()
    # priority 2 (RBAC ownership): Seller may only credit themselves.
    seller_id = require_str(body, "seller_id")
    validation.enforce_seller_ownership(seller_id)
    # priority 4: reference existence — campaign, seller within campaign.
    campaign_id = require_str(body, "campaign_id")
    campaign = validation.resolve_campaign_ref(campaign_id)
    validation.resolve_seller_ref(seller_id, campaign_id)
    # priority 5: body shape.
    donor_name = require_str(body, "donor_name")
    donor_email = require_str(body, "donor_email")
    per_unit_cents = require_int(body, "per_unit_cents")
    flat_cents = opt_int(body, "flat_cents", 0)
    cap_cents = opt_int(body, "cap_cents", 0)
    if per_unit_cents < 0:
        raise errors.invalid_request("per_unit_cents must be at least 0")
    if flat_cents < 0:
        raise errors.invalid_request("flat_cents must be at least 0")
    if cap_cents < 0:
        raise errors.invalid_request("cap_cents must be at least 0")
    with lock:
        # priority 8: posture gate — pledge create requires ACTIVE.
        validation.require_campaign_active_for_create(campaign)
        pid = new_id()
        ts = now_ts()
        pledge = {
            "id": pid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "seller_id": seller_id,
            "donor_name": donor_name,
            "donor_email": donor_email,
            "per_unit_cents": per_unit_cents,
            "flat_cents": flat_cents,
            "cap_cents": cap_cents,
            "units_recorded": 0,
            "status": "PROMISED",
            "collected_cents": 0,
            "receipt_number": None,
        }
        db.pledges[pid] = pledge
    return success(serializers.pledge(pledge), status=201)


@bp.route("/fundraising/pledges", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_pledges():
    items = list(db.pledges.values())
    campaign_id = request.args.get("campaign_id")
    seller_id = request.args.get("seller_id")
    status = request.args.get("status")
    if campaign_id is not None:
        items = [p for p in items if p["campaign_id"] == campaign_id]
    if seller_id is not None:
        items = [p for p in items if p["seller_id"] == seller_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate_and_respond(items, serializers.pledge)


@bp.route("/fundraising/pledges/<pledge_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial", "Seller")
def get_pledge_route(pledge_id):
    p = get_pledge(pledge_id)
    validation.enforce_seller_reads_own(p["seller_id"])
    return success(serializers.pledge(p), status=200)


@bp.route("/fundraising/pledges/<pledge_id>/record", methods=["POST"])
@require_roles("CampaignAdmin")
def record(pledge_id):
    p = get_pledge(pledge_id)
    campaign = get_campaign(p["campaign_id"])
    body = get_body()
    units_recorded = require_int(body, "units_recorded")
    if units_recorded < 0:
        raise errors.invalid_request("units_recorded must be at least 0")
    with lock:
        # priority 7: state legality.
        if p["status"] != "PROMISED":
            raise errors.invalid_state("Pledge must be PROMISED to record")
        # priority 8: posture gate.
        validation.require_campaign_active(campaign)
        # priority 9: seller-block guard.
        seller = get_seller(p["seller_id"])
        if seller["status"] == "BLOCKED":
            raise errors.seller_blocked()
        p["units_recorded"] = units_recorded
        p["status"] = "RECORDED"
        touch(p)
    return success(serializers.pledge(p), status=200)


@bp.route("/fundraising/pledges/<pledge_id>/revise", methods=["POST"])
@require_roles("CampaignAdmin")
def revise(pledge_id):
    p = get_pledge(pledge_id)
    campaign = get_campaign(p["campaign_id"])
    with lock:
        # priority 7: state legality.
        if p["status"] != "RECORDED":
            raise errors.invalid_state("Pledge must be RECORDED to revise")
        # priority 8: posture gate.
        validation.require_campaign_active(campaign)
        p["units_recorded"] = 0
        p["status"] = "PROMISED"
        touch(p)
    return success(serializers.pledge(p), status=200)


@bp.route("/fundraising/pledges/<pledge_id>/collect", methods=["POST"])
@require_roles("CampaignAdmin")
def collect(pledge_id):
    p = get_pledge(pledge_id)
    campaign = get_campaign(p["campaign_id"])
    with lock:
        # priority 7: state legality.
        if p["status"] != "RECORDED":
            raise errors.invalid_state("Pledge must be RECORDED to collect")
        # priority 8: posture gate — collect allowed in ACTIVE or CLOSED.
        if campaign["posture"] not in ("ACTIVE", "CLOSED"):
            raise errors.campaign_not_active(
                "Collect requires campaign posture ACTIVE or CLOSED")
        # priority 9: seller-block guard.
        seller = get_seller(p["seller_id"])
        if seller["status"] == "BLOCKED":
            raise errors.seller_blocked()
        p["collected_cents"] = calc.compute_pledged_amount(p)
        p["status"] = "COLLECTED"
        p["receipt_number"] = db.next_receipt()
        touch(p)
    return success(serializers.pledge(p), status=200)


@bp.route("/fundraising/pledges/<pledge_id>/cancel", methods=["POST"])
@require_roles("CampaignAdmin")
def cancel(pledge_id):
    p = get_pledge(pledge_id)
    with lock:
        # priority 7: state legality — cancel legal from PROMISED or RECORDED.
        if p["status"] not in ("PROMISED", "RECORDED"):
            raise errors.invalid_state("Pledge must be PROMISED or RECORDED to cancel")
        p["status"] = "CANCELLED"
        touch(p)
    return success(serializers.pledge(p), status=200)
