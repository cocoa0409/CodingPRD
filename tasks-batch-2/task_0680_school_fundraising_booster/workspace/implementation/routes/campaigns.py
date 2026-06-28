"""Campaign routes: create, get, list, report, and posture lifecycle.

Lifecycle: DRAFT -> ACTIVE -> CLOSED -> RECONCILED -> DISBURSED, with FROZEN
reachable from ACTIVE and back. reconcile/disburse are Treasurer-only and carry
optimistic concurrency on Campaign.version.
"""

from flask import Blueprint

import errors
import serializers
from db import db, lock, new_id, now_ts
from clock import clock, format_iso8601_ms
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_enum, require_int,
                     require_number, opt_str, parse_pagination)
from response import list_success
from lookups import get_campaign
from clock import parse_iso8601
from services import calc
from services.mutations import touch, cascade_close_campaign

bp = Blueprint("campaigns", __name__)

CAMPAIGN_TYPES = {"CATALOG", "PLEDGE", "EVENT"}


def _validate_window(starts_at, ends_at):
    try:
        s = parse_iso8601(starts_at)
        e = parse_iso8601(ends_at)
    except (ValueError, TypeError):
        raise errors.invalid_request("starts_at / ends_at must be valid ISO 8601")
    if not (e > s):
        raise errors.invalid_request("ends_at must be strictly after starts_at")


@bp.route("/fundraising/campaigns", methods=["POST"])
@require_roles("CampaignAdmin")
def create_campaign():
    body = get_body()
    name = require_str(body, "name")
    campaign_type = require_enum(body, "campaign_type", CAMPAIGN_TYPES)
    goal_cents = require_int(body, "goal_cents")
    if goal_cents < 1:
        raise errors.invalid_request("goal_cents must be at least 1")
    profit_split_pct = require_number(body, "profit_split_pct")
    if not (profit_split_pct > 0 and profit_split_pct <= 1):
        raise errors.invalid_request("profit_split_pct must be in (0, 1]")
    vendor_name = require_str(body, "vendor_name")
    starts_at = require_str(body, "starts_at")
    ends_at = require_str(body, "ends_at")
    _validate_window(starts_at, ends_at)

    with lock:
        cid = new_id()
        ts = now_ts()
        campaign = {
            "id": cid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "name": name,
            "campaign_type": campaign_type,
            "goal_cents": goal_cents,
            "profit_split_pct": profit_split_pct,
            "vendor_name": vendor_name,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "posture": "DRAFT",
            "school_profit_cents": 0,
            "vendor_payable_cents": 0,
            "reconciled_at": None,
        }
        db.campaigns[cid] = campaign
    return success(serializers.campaign(campaign), status=201)


@bp.route("/fundraising/campaigns", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def list_campaigns():
    posture = None
    campaign_type = None
    from flask import request
    posture = request.args.get("posture")
    campaign_type = request.args.get("campaign_type")
    items = list(db.campaigns.values())
    if posture is not None:
        items = [c for c in items if c["posture"] == posture]
    if campaign_type is not None:
        items = [c for c in items if c["campaign_type"] == campaign_type]
    items = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([serializers.campaign(c) for c in page], limit, offset, total)


@bp.route("/fundraising/campaigns/<campaign_id>", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def get_campaign_route(campaign_id):
    c = get_campaign(campaign_id)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/report", methods=["GET"])
@require_roles("CampaignAdmin", "Treasurer", "SchoolOfficial")
def report(campaign_id):
    c = get_campaign(campaign_id)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/activate", methods=["POST"])
@require_roles("CampaignAdmin")
def activate(campaign_id):
    c = get_campaign(campaign_id)
    with lock:
        if c["posture"] != "DRAFT":
            raise errors.invalid_state("Campaign must be DRAFT to activate")
        has_seller = any(s["campaign_id"] == campaign_id for s in db.sellers.values())
        has_prize = any(t["campaign_id"] == campaign_id for t in db.prize_tiers.values())
        if not has_seller:
            raise errors.invalid_state("Campaign needs at least one Seller to activate")
        if not (has_prize or c["campaign_type"] == "EVENT"):
            raise errors.invalid_state(
                "Campaign needs at least one PrizeTier (unless EVENT) to activate")
        c["posture"] = "ACTIVE"
        touch(c)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/freeze", methods=["POST"])
@require_roles("CampaignAdmin")
def freeze(campaign_id):
    c = get_campaign(campaign_id)
    with lock:
        if c["posture"] != "ACTIVE":
            raise errors.invalid_state("Campaign must be ACTIVE to freeze")
        c["posture"] = "FROZEN"
        touch(c)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/unfreeze", methods=["POST"])
@require_roles("CampaignAdmin")
def unfreeze(campaign_id):
    c = get_campaign(campaign_id)
    with lock:
        if c["posture"] != "FROZEN":
            raise errors.invalid_state("Campaign must be FROZEN to unfreeze")
        c["posture"] = "ACTIVE"
        touch(c)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/close", methods=["POST"])
@require_roles("CampaignAdmin")
def close(campaign_id):
    c = get_campaign(campaign_id)
    with lock:
        if c["posture"] != "ACTIVE":
            raise errors.invalid_state("Campaign must be ACTIVE to close")
        c["posture"] = "CLOSED"
        touch(c)
        cascade_close_campaign(c)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/reconcile", methods=["POST"])
@require_roles("Treasurer")
def reconcile(campaign_id):
    c = get_campaign(campaign_id)
    body = get_body()
    expected = require_int(body, "expected_campaign_version")
    with lock:
        # priority 6: OCC before state legality (PRD §2.9).
        if expected != c["version"]:
            raise errors.stale_campaign_version()
        # priority 7: state legality.
        if c["posture"] != "CLOSED":
            raise errors.invalid_state("Campaign must be CLOSED to reconcile")
        products_by_id = {p["id"]: p for p in db.products.values()
                          if p["campaign_id"] == campaign_id}
        school_profit, vendor_payable = calc.compute_profit_split(c, products_by_id)
        c["school_profit_cents"] = school_profit
        c["vendor_payable_cents"] = vendor_payable
        c["reconciled_at"] = format_iso8601_ms(clock.now())
        c["posture"] = "RECONCILED"
        touch(c)
    return success(serializers.campaign(c), status=200)


@bp.route("/fundraising/campaigns/<campaign_id>/disburse", methods=["POST"])
@require_roles("Treasurer")
def disburse(campaign_id):
    c = get_campaign(campaign_id)
    body = get_body()
    expected = require_int(body, "expected_campaign_version")
    memo = opt_str(body, "memo", None)
    with lock:
        # priority 6: OCC before state legality (PRD §2.9).
        if expected != c["version"]:
            raise errors.stale_campaign_version()
        # priority 7: state legality (also bars double disbursement).
        if c["posture"] != "RECONCILED":
            raise errors.invalid_state("Campaign must be RECONCILED to disburse")
        did = new_id()
        ts = now_ts()
        disb = {
            "id": did,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "campaign_id": campaign_id,
            "school_amount_cents": c["school_profit_cents"],
            "vendor_amount_cents": c["vendor_payable_cents"],
            "memo": memo,
            "status": "RECORDED",
        }
        db.disbursements[did] = disb
        c["posture"] = "DISBURSED"
        touch(c)
    return success(serializers.campaign(c), status=200)
