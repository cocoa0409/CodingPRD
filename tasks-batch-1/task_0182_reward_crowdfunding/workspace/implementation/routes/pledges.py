"""Pledge create/cancel, add-on attach, survey, ship, and authorization queueing."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_OWNER, ERR_FK_INVALID, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_CAMPAIGN_NOT_LIVE, ERR_PLEDGE_BELOW_TIER_MIN,
    ERR_CURRENCY_MISMATCH, ERR_TIER_SOLD_OUT, ERR_ADDON_SOLD_OUT,
    ERR_STALE_CAMPAIGN_VERSION, ERR_SURVEY_NOT_READY,
)
from middleware import require_role
from response import success, list_response
from services import domain
from util import (
    get_json_body, require_positive_int, require_int, require_enum, require_str,
    parse_dt, parse_pagination, paginate,
)

bp = Blueprint("pledges", __name__)

ZONES = {"DOMESTIC", "INTL"}


# ---------------------------------------------------------------------------
# Create pledge — full validation precedence (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/campaigns/<campaign_id>/pledges", methods=["POST"])
def create_pledge(campaign_id):
    # 1 auth presence, 2 role
    user_id, role = require_role(["Backer"])

    # 3 path existence
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")

    body = get_json_body()

    # 4 FK resolution: tier_id belongs to this campaign; backer_id is real.
    tier_id = body.get("tier_id")
    backer_id = body.get("backer_id")
    if not isinstance(tier_id, str) or not isinstance(backer_id, str):
        # Missing/malformed FK fields surface as FK-invalid at this stage.
        raise err(ERR_FK_INVALID, "tier_id and backer_id are required references")
    tier = db.tiers.get(tier_id)
    if tier is None or tier["campaign_id"] != campaign_id:
        raise err(ERR_FK_INVALID, "tier_id does not belong to this campaign")
    backer = db.backers.get(backer_id)
    if backer is None:
        raise err(ERR_FK_INVALID, "backer_id does not resolve")

    # 5 body well-formedness
    pledge_amount = require_positive_int(body, "pledge_amount_cents")
    destination_zone = require_enum(body, "destination_zone", ZONES)
    expected_version = body.get("expected_campaign_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err(ERR_INVALID_REQUEST, "expected_campaign_version is required (integer)")

    # 6 ownership: acting backer must be the pledging backer.
    if backer_id != user_id:
        raise err(ERR_NOT_OWNER, "Backer may only pledge as themselves")

    # 7 state: for pledge-create there is no campaign state that fails ERR_INVALID_STATE
    #   distinctly from the live-window temporal gate. PRD §3.5 assigns the
    #   "campaign is not live" condition explicitly to ERR_CAMPAIGN_NOT_LIVE, so the
    #   not-LIVE case is handled by the temporal gate below (priority 8), not here.

    # 8 temporal: pledging is allowed only while the campaign is LIVE and clock <
    #   deadline. A pledge against a campaign that is not live, OR whose deadline has
    #   passed, is rejected with ERR_CAMPAIGN_NOT_LIVE (PRD §3.5).
    clock = parse_dt(db.clock)
    deadline = parse_dt(campaign["deadline_utc"])
    if campaign["status"] != "LIVE" or clock >= deadline:
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Campaign is not live or its deadline has passed")

    # 9 pledge amount >= tier.price_cents
    if pledge_amount < tier["price_cents"]:
        raise err(ERR_PLEDGE_BELOW_TIER_MIN, "pledge_amount_cents below tier minimum")

    # 11 tier inventory (priority 11; currency mismatch priority 10 is add-on only)
    if tier["status"] != "AVAILABLE":
        raise err(ERR_TIER_SOLD_OUT, "Tier is not available")
    if (tier["limit_quantity"] is not None
            and tier["claimed_quantity"] >= tier["limit_quantity"]):
        raise err(ERR_TIER_SOLD_OUT, "Tier is sold out")

    # 13 OCC on campaign.version
    if expected_version != campaign["version"]:
        raise err(ERR_STALE_CAMPAIGN_VERSION, "expected_campaign_version is stale")

    # --- accept ---
    rec = {
        "campaign_id": campaign_id,
        "backer_id": backer_id,
        "tier_id": tier_id,
        "pledge_amount_cents": pledge_amount,
        "destination_zone": destination_zone,
        "items_subtotal_cents": 0,
        "shipping_cents": 0,
        "committed_amount_cents": 0,
        "payment_status": "PENDING_AUTH",
        "fulfillment_status": "NOT_STARTED",
        "status": "ACTIVE",
    }
    domain._stamp_new(rec, versioned=True)
    db.pledges[rec["id"]] = rec
    domain.recompute_pledge_total(rec)

    # Cascades: tier claimed_quantity (may flip SOLD_OUT), projected raise,
    # stretch-goal unlock, campaign version bump.
    domain.recompute_tier_claimed(tier)
    domain.recompute_projected_raise(campaign)
    domain.reconcile_stretch_goals(campaign)
    domain.touch(campaign)

    return success(domain.serialize(rec), status=201)


@bp.route("/pledges", methods=["GET"])
def list_pledges():
    require_role(["PlatformAdmin", "Creator", "Backer"])
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    backer_id = request.args.get("backer_id")
    tier_id = request.args.get("tier_id")
    records = list(db.pledges.values())
    if campaign_id is not None:
        records = [p for p in records if p["campaign_id"] == campaign_id]
    if backer_id is not None:
        records = [p for p in records if p["backer_id"] == backer_id]
    if tier_id is not None:
        records = [p for p in records if p["tier_id"] == tier_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(p) for p in window], limit, offset, total)


@bp.route("/pledges/<pledge_id>", methods=["GET"])
def get_pledge(pledge_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.pledges.get(pledge_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")
    return success(domain.serialize(rec), status=200)


# ---------------------------------------------------------------------------
# Attach add-on line (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/pledges/<pledge_id>/add-ons", methods=["POST"])
def attach_addon(pledge_id):
    user_id, role = require_role(["Backer"])
    pledge = db.pledges.get(pledge_id)
    if pledge is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")

    body = get_json_body()

    # FK resolution: addon_id must resolve.
    addon_id = body.get("addon_id")
    if not isinstance(addon_id, str):
        raise err(ERR_FK_INVALID, "addon_id is required")
    addon = db.addons.get(addon_id)
    if addon is None:
        raise err(ERR_FK_INVALID, "addon_id does not resolve")

    # Well-formedness.
    quantity = require_positive_int(body, "quantity")

    # Ownership: backer owns the pledge.
    if pledge["backer_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Backer does not own this pledge")

    campaign = db.campaigns.get(pledge["campaign_id"])

    # State: pledge must still be ACTIVE.
    if pledge["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Pledge is not ACTIVE")

    # Temporal: campaign LIVE and clock < deadline.
    if campaign is None or campaign["status"] != "LIVE":
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Campaign is not LIVE")
    clock = parse_dt(db.clock)
    deadline = parse_dt(campaign["deadline_utc"])
    if clock >= deadline:
        raise err(ERR_CAMPAIGN_NOT_LIVE, "Campaign deadline has passed")

    # Currency / same-campaign check (priority 10).
    if addon["campaign_id"] != pledge["campaign_id"]:
        raise err(ERR_CURRENCY_MISMATCH, "Add-on belongs to a different campaign")

    # Add-on inventory (priority 12): claimed + requested must not exceed limit.
    if (addon["limit_quantity"] is not None
            and addon["claimed_quantity"] + quantity > addon["limit_quantity"]):
        raise err(ERR_ADDON_SOLD_OUT, "Add-on would exceed its limit quantity")

    line = {
        "pledge_id": pledge_id,
        "addon_id": addon_id,
        "quantity": quantity,
        "line_total_cents": quantity * addon["price_cents"],
    }
    domain._stamp_new(line, versioned=False)
    db.pledge_addons[line["id"]] = line

    # Recompute pledge money + add-on claimed + projected raise.
    domain.recompute_pledge_total(pledge)
    domain.touch(pledge)
    domain.recompute_addon_claimed(addon)
    domain.recompute_projected_raise(campaign)
    domain.reconcile_stretch_goals(campaign)
    domain.touch(campaign)

    return success(domain.serialize(line), status=201)


# ---------------------------------------------------------------------------
# Cancel own pledge (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/pledges/<pledge_id>/cancel", methods=["POST"])
def cancel_pledge(pledge_id):
    user_id, role = require_role(["Backer"])
    pledge = db.pledges.get(pledge_id)
    if pledge is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")

    if pledge["backer_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Backer does not own this pledge")

    # State: must be ACTIVE.
    if pledge["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Pledge is not ACTIVE")

    # State: cancel is permitted only "while the campaign is LIVE" (PRD §3.5).
    #   ERR_CAMPAIGN_NOT_LIVE is reserved by PRD prose for pledge-create / add-on
    #   attach; a cancel against a campaign that is not LIVE is a generic invalid
    #   state transition -> ERR_INVALID_STATE.
    campaign = db.campaigns.get(pledge["campaign_id"])
    if campaign is None or campaign["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "Campaign is not LIVE; pledge cannot be canceled")

    pledge["status"] = "CANCELED"
    domain.touch(pledge)

    # Release tier + add-on inventory.
    domain.release_pledge_inventory(pledge)
    domain.recompute_projected_raise(campaign)
    domain.reconcile_stretch_goals(campaign)
    domain.touch(campaign)

    return success(domain.serialize(pledge), status=200)


# ---------------------------------------------------------------------------
# Complete survey (PRD §3.11) — SURVEY_SENT -> SURVEY_COMPLETE
# ---------------------------------------------------------------------------
@bp.route("/pledges/<pledge_id>/survey", methods=["POST"])
def complete_survey(pledge_id):
    user_id, role = require_role(["Backer"])
    pledge = db.pledges.get(pledge_id)
    if pledge is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")

    body = get_json_body()
    shipping_address = require_str(body, "shipping_address")

    if pledge["backer_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Backer does not own this pledge")

    # Survey readiness: payment_status CAPTURED and an existing incomplete survey.
    if pledge["payment_status"] != "CAPTURED":
        raise err(ERR_SURVEY_NOT_READY, "Pledge is not CAPTURED")
    survey = _pledge_survey(pledge_id)
    if survey is None or survey["completed"]:
        raise err(ERR_SURVEY_NOT_READY, "No incomplete survey for this pledge")

    survey["shipping_address"] = shipping_address
    survey["completed"] = True
    domain.touch(survey)

    pledge["fulfillment_status"] = "SURVEY_COMPLETE"
    domain.touch(pledge)

    return success(domain.serialize(pledge), status=200)


# ---------------------------------------------------------------------------
# Ship (PRD §3.11) — SURVEY_COMPLETE -> SHIPPED
# ---------------------------------------------------------------------------
@bp.route("/pledges/<pledge_id>/ship", methods=["POST"])
def ship_pledge(pledge_id):
    user_id, role = require_role(["Creator"])
    pledge = db.pledges.get(pledge_id)
    if pledge is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")

    campaign = db.campaigns.get(pledge["campaign_id"])
    if campaign is None or campaign["creator_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Acting creator does not own the owning campaign")

    if pledge["fulfillment_status"] != "SURVEY_COMPLETE":
        raise err(ERR_INVALID_STATE, "Pledge fulfillment is not SURVEY_COMPLETE")

    pledge["fulfillment_status"] = "SHIPPED"
    domain.touch(pledge)
    return success(domain.serialize(pledge), status=200)


# ---------------------------------------------------------------------------
# Queue authorization (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/pledges/<pledge_id>/authorization", methods=["POST"])
def queue_authorization(pledge_id):
    require_role(["PlatformAdmin"])
    pledge = db.pledges.get(pledge_id)
    if pledge is None:
        raise err(ERR_NOT_FOUND, "Pledge not found")

    body = get_json_body()
    outcome = require_enum(body, "outcome", {"SUCCEEDED", "DECLINED"})

    rec = {
        "pledge_id": pledge_id,
        "outcome": outcome,
        "amount_cents": pledge["committed_amount_cents"],
    }
    domain._stamp_new(rec, versioned=False)
    db.authorizations[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


def _pledge_survey(pledge_id):
    for s in db.surveys.values():
        if s["pledge_id"] == pledge_id:
            return s
    return None
