"""Campaign CRUD, lifecycle (launch/close/cancel), and settlement read."""
from flask import Blueprint, request

from db import db
from errors import (
    err, ERR_NOT_FOUND, ERR_NOT_OWNER, ERR_INVALID_STATE, ERR_NO_TIERS,
    ERR_DEADLINE_IN_PAST, ERR_CAMPAIGN_WINDOW_OVERLAP, ERR_NOT_CLOSABLE,
    ERR_INVALID_REQUEST,
)
from middleware import require_role
from response import success, list_response
from services import domain, calc
from util import (
    get_json_body, require_str, require_positive_int, require_enum, parse_dt,
    parse_pagination, paginate,
)

bp = Blueprint("campaigns", __name__)

FUNDING_MODELS = {"ALL_OR_NOTHING", "FLEXIBLE"}


@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    user_id, role = require_role(["Creator"])
    body = get_json_body()

    # Body well-formedness (ERR_INVALID_REQUEST) before FK resolution of creator.
    creator_id = require_str(body, "creator_id")
    title = require_str(body, "title")
    funding_goal = require_positive_int(body, "funding_goal_cents")
    funding_model = require_enum(body, "funding_model", FUNDING_MODELS)
    deadline_raw = body.get("deadline_utc")
    deadline = parse_dt(deadline_raw)
    if deadline is None:
        raise err(ERR_INVALID_REQUEST,
                  "deadline_utc must be an ISO 8601 UTC timestamp")

    creator = db.creators.get(creator_id)
    if creator is None:
        raise err(ERR_NOT_FOUND, "Creator not found")

    # Creator is entity-backed: may only create campaigns owned by themselves.
    if creator_id != user_id:
        raise err(ERR_NOT_OWNER, "Creator may only create campaigns it owns")

    rec = {
        "creator_id": creator_id,
        "title": title,
        "currency": creator["payout_currency"],
        "funding_goal_cents": funding_goal,
        "funding_model": funding_model,
        "deadline_utc": body["deadline_utc"],
        "status": "DRAFT",
        "committed_amount_cents": 0,
        "settled_amount_cents": None,
        "goal_met": None,
        "launched_at": None,
    }
    domain._stamp_new(rec, versioned=True)
    db.campaigns[rec["id"]] = rec
    return success(domain.serialize(rec), status=201)


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    require_role(["PlatformAdmin", "Creator", "Backer"])
    limit, offset = parse_pagination()
    creator_id = request.args.get("creator_id")
    records = list(db.campaigns.values())
    if creator_id is not None:
        records = [c for c in records if c["creator_id"] == creator_id]
    window, total = paginate(records, limit, offset)
    return list_response([domain.serialize(c) for c in window], limit, offset, total)


@bp.route("/campaigns/<campaign_id>", methods=["GET"])
def get_campaign(campaign_id):
    require_role(["PlatformAdmin", "Creator", "Backer"])
    rec = db.campaigns.get(campaign_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")
    return success(domain.serialize(rec), status=200)


def _load_owned_campaign(campaign_id, user_id, allowed_status=None):
    """Resolve campaign (404), then verify owner (ERR_NOT_OWNER)."""
    rec = db.campaigns.get(campaign_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")
    if rec["creator_id"] != user_id:
        raise err(ERR_NOT_OWNER, "Acting creator does not own this campaign")
    return rec


@bp.route("/campaigns/<campaign_id>/launch", methods=["POST"])
def launch_campaign(campaign_id):
    user_id, role = require_role(["Creator"])
    campaign = _load_owned_campaign(campaign_id, user_id)

    # State: must be DRAFT.
    if campaign["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Campaign must be DRAFT to launch")

    # At least one AVAILABLE tier.
    tiers = domain.get_campaign_tiers(campaign_id)
    if not any(t["status"] == "AVAILABLE" for t in tiers):
        raise err(ERR_NO_TIERS, "Campaign has no AVAILABLE reward tier")

    # deadline strictly after current clock.
    clock = parse_dt(db.clock)
    deadline = parse_dt(campaign["deadline_utc"])
    if not (deadline > clock):
        raise err(ERR_DEADLINE_IN_PAST, "deadline_utc must be strictly after now")

    # Same-creator live-window overlap. New window [clock, deadline).
    for other in db.campaigns.values():
        if other["id"] == campaign_id:
            continue
        if other["creator_id"] != campaign["creator_id"]:
            continue
        if other["status"] != "LIVE":
            continue
        other_deadline = parse_dt(other["deadline_utc"])
        other_launched = parse_dt(other["launched_at"])
        # overlap iff clock < other.deadline AND other.launched < this.deadline
        if clock < other_deadline and other_launched < deadline:
            raise err(ERR_CAMPAIGN_WINDOW_OVERLAP,
                      "Live window overlaps another LIVE campaign of the same creator")

    campaign["status"] = "LIVE"
    campaign["launched_at"] = db.clock
    campaign["committed_amount_cents"] = 0
    domain.touch(campaign)
    return success(domain.serialize(campaign), status=200)


@bp.route("/campaigns/<campaign_id>/close", methods=["POST"])
def close_campaign(campaign_id):
    require_role(["PlatformAdmin"])
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")

    # State: must be LIVE.
    if campaign["status"] != "LIVE":
        raise err(ERR_INVALID_STATE, "Campaign must be LIVE to close")

    # Closable only once clock >= deadline.
    clock = parse_dt(db.clock)
    deadline = parse_dt(campaign["deadline_utc"])
    if clock < deadline:
        raise err(ERR_NOT_CLOSABLE, "Clock has not yet reached campaign deadline")

    domain.settle_campaign(campaign)
    return success(domain.serialize(campaign), status=200)


@bp.route("/campaigns/<campaign_id>/cancel", methods=["POST"])
def cancel_campaign(campaign_id):
    user_id, role = require_role(["Creator"])
    campaign = _load_owned_campaign(campaign_id, user_id)

    if campaign["status"] not in ("DRAFT", "LIVE"):
        raise err(ERR_INVALID_STATE, "Campaign must be DRAFT or LIVE to cancel")

    domain.cancel_campaign(campaign)
    return success(domain.serialize(campaign), status=200)


@bp.route("/campaigns/<campaign_id>/settlement", methods=["GET"])
def get_settlement(campaign_id):
    require_role(["PlatformAdmin", "Creator"])
    campaign = db.campaigns.get(campaign_id)
    if campaign is None:
        raise err(ERR_NOT_FOUND, "Campaign not found")

    captured = [p for p in domain.get_campaign_pledges(campaign_id)
                if p["payment_status"] == "CAPTURED"]
    platform_fee = sum(calc.per_pledge_fee_cents(p["committed_amount_cents"])
                       for p in captured)
    settled = campaign.get("settled_amount_cents") or 0
    payout = settled - platform_fee
    return success({
        "settled_amount_cents": campaign.get("settled_amount_cents"),
        "platform_fee_cents": platform_fee,
        "creator_payout_cents": payout,
        "captured_pledge_count": len(captured),
    }, status=200)
