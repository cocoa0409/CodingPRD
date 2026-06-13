"""RewardTier, StretchGoal, and AddOn (add-on-product) endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_OWNER, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_TIER_WINDOW_OVERLAP,
)
from middleware import require_role
from response import success, list_response
from services import domain, calc
from util import (
    get_json_body, require_str, require_positive_int, require_nonneg_int,
    optional_limit_quantity, parse_dt, parse_pagination, paginate,
)

bp = Blueprint("catalog", __name__)


def _owned_campaign(campaign_id, user_id):
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")
    if campaign["creator_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Acting creator does not own this campaign")
    return campaign


# ---------------------------------------------------------------------------
# RewardTier
# ---------------------------------------------------------------------------
@bp.route("/campaigns/<campaign_id>/tiers", methods=["POST"])
def create_tier(campaign_id):
    user_id, role = require_role(["Creator"])
    campaign = _owned_campaign(campaign_id, user_id)
    body = get_json_body()

    # Well-formedness.
    title = require_str(body, "title")
    price = require_positive_int(body, "price_cents")
    limit_quantity = optional_limit_quantity(body)
    weight = require_nonneg_int(body, "weight_grams")
    is_early_bird = body.get("is_early_bird", False)
    if not isinstance(is_early_bird, bool):
        raise err(ERR_INVALID_REQUEST, "is_early_bird must be a boolean")

    available_from_raw = body.get("available_from")
    available_until_raw = body.get("available_until")
    available_from = None
    available_until = None
    if is_early_bird:
        available_from = parse_dt(available_from_raw)
        available_until = parse_dt(available_until_raw)
        if available_from is None or available_until is None:
            raise err(ERR_INVALID_REQUEST,
                      "Early-bird tier requires available_from and available_until")
        if not (available_until > available_from):
            raise err(ERR_INVALID_REQUEST,
                      "available_until must be strictly after available_from")
    else:
        # window fields null when not early bird
        available_from_raw = None
        available_until_raw = None

    # State: tiers only while DRAFT.
    if campaign["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Tiers may only be created while campaign is DRAFT")

    # Early-bird window-gap overlap check against existing early-bird tiers.
    if is_early_bird:
        gap = calc.TIER_GAP_SECONDS
        for other in domain.get_campaign_tiers(campaign_id):
            if not other.get("is_early_bird"):
                continue
            e0 = parse_dt(other["available_from"])
            e1 = parse_dt(other["available_until"])
            if e0 is None or e1 is None:
                continue
            n0, n1 = available_from, available_until
            # reject if (n0 < e1 + gap) AND (e0 < n1 + gap)
            if (n0.timestamp() < e1.timestamp() + gap
                    and e0.timestamp() < n1.timestamp() + gap):
                raise err(ERR_TIER_WINDOW_OVERLAP,
                          "Early-bird window within TIER_GAP_SECONDS of an existing one")

    rec = {
        "campaign_id": campaign_id,
        "title": title,
        "price_cents": price,
        "limit_quantity": limit_quantity,
        "claimed_quantity": 0,
        "weight_grams": weight,
        "is_early_bird": is_early_bird,
        "available_from": available_from_raw,
        "available_until": available_until_raw,
        "status": "AVAILABLE",
    }
    domain._stamp_new(rec, versioned=True)
    db.tiers[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/tiers", methods=["GET"])
def list_tiers():
    require_role(["PlatformAdmin", "Creator", "Backer"])
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    records = list(db.tiers.values())
    if campaign_id is not None:
        records = [t for t in records if t["campaign_id"] == campaign_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(t) for t in window], limit, offset, total)


@bp.route("/tiers/<tier_id>", methods=["GET"])
def get_tier(tier_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.tiers.get(tier_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Tier not found")
    return success(domain.serialize(rec), status=200)


# ---------------------------------------------------------------------------
# StretchGoal
# ---------------------------------------------------------------------------
@bp.route("/campaigns/<campaign_id>/stretch-goals", methods=["POST"])
def create_stretch_goal(campaign_id):
    user_id, role = require_role(["Creator"])
    campaign = _owned_campaign(campaign_id, user_id)
    body = get_json_body()

    title = require_str(body, "title")
    threshold = require_positive_int(body, "threshold_cents")
    # threshold must be strictly greater than the campaign's funding goal.
    if threshold <= campaign["funding_goal_cents"]:
        raise err(ERR_INVALID_REQUEST,
                  "threshold_cents must be greater than campaign funding_goal_cents")

    if campaign["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  "Stretch goals may only be created while campaign is DRAFT")

    rec = {
        "campaign_id": campaign_id,
        "title": title,
        "threshold_cents": threshold,
        "unlocked": False,
    }
    domain._stamp_new(rec, versioned=True)
    db.stretch_goals[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/stretch-goals", methods=["GET"])
def list_stretch_goals():
    require_role(["PlatformAdmin", "Creator", "Backer"])
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    records = list(db.stretch_goals.values())
    if campaign_id is not None:
        records = [s for s in records if s["campaign_id"] == campaign_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(s) for s in window], limit, offset, total)


@bp.route("/stretch-goals/<stretch_goal_id>", methods=["GET"])
def get_stretch_goal(stretch_goal_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.stretch_goals.get(stretch_goal_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Stretch goal not found")
    return success(domain.serialize(rec), status=200)


# ---------------------------------------------------------------------------
# AddOn product
# ---------------------------------------------------------------------------
@bp.route("/campaigns/<campaign_id>/add-on-products", methods=["POST"])
def create_addon(campaign_id):
    user_id, role = require_role(["Creator"])
    campaign = _owned_campaign(campaign_id, user_id)
    body = get_json_body()

    title = require_str(body, "title")
    price = require_positive_int(body, "price_cents")
    limit_quantity = optional_limit_quantity(body)
    weight = require_nonneg_int(body, "weight_grams")

    # Add-on products only while DRAFT or LIVE.
    if campaign["status"] not in ("DRAFT", "LIVE"):
        raise err(ERR_INVALID_STATE,
                  "Add-on products may only be created while campaign is DRAFT or LIVE")

    rec = {
        "campaign_id": campaign_id,
        "title": title,
        "price_cents": price,
        "limit_quantity": limit_quantity,
        "claimed_quantity": 0,
        "weight_grams": weight,
    }
    domain._stamp_new(rec, versioned=True)
    db.addons[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/add-on-products", methods=["GET"])
def list_addons():
    require_role(["PlatformAdmin", "Creator", "Backer"])
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    records = list(db.addons.values())
    if campaign_id is not None:
        records = [a for a in records if a["campaign_id"] == campaign_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(a) for a in window], limit, offset, total)


@bp.route("/add-on-products/<addon_id>", methods=["GET"])
def get_addon(addon_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.addons.get(addon_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Add-on product not found")
    return success(domain.serialize(rec), status=200)
