"""Creator endpoints: onboard, list, get, metrics update, lifecycle
transitions (incl. exit guard and suspension cascades)."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import calc, helpers as H, lifecycle

bp = Blueprint("creators", __name__)


@bp.route("/creators", methods=["POST"])
@require_roles("TalentManager")
def create_creator(actor):
    payload = H.body()
    H.req_fields(payload, ["handle", "email", "niche", "primary_platform",
                           "followers", "avg_views_30d", "engagement_rate_bps"])
    handle = H.require_str(payload, "handle")
    email = H.require_str(payload, "email")
    niche = H.require_enum(payload, "niche", H.NICHE_ENUM)
    platform = H.require_enum(payload, "primary_platform", H.PLATFORM_ENUM)
    followers = H.require_int(payload, "followers", minimum=0)
    avg_views = H.require_int(payload, "avg_views_30d", minimum=0)
    eng_bps = H.require_int(payload, "engagement_rate_bps", minimum=0)

    for c in db.creators.values():
        if c["handle"] == handle:
            raise err.validation(f"handle must be unique: {handle}")

    creator = H.new_entity()
    creator.update({
        "handle": handle,
        "email": email,
        "niche": niche,
        "primary_platform": platform,
        "followers": followers,
        "avg_views_30d": avg_views,
        "engagement_rate_bps": eng_bps,
        "status": "APPLIED",
        "rate_card_cpm_cents": None,
        "rate_card_flat_cents": None,
        "compliance_strikes": 0,
        "lifetime_billed_cents": 0,
        "pending_disclosure_count": 0,
    })
    db.creators[creator["id"]] = creator
    return resp.created(creator)


@bp.route("/creators", methods=["GET"])
@require_roles("TalentManager", "BrandManager", "FinanceAdmin", "ComplianceOfficer")
def list_creators(actor):
    items = list(db.creators.values())
    status = request.args.get("status")
    niche = request.args.get("niche")
    min_followers = request.args.get("min_followers")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if niche is not None:
        items = [c for c in items if c["niche"] == niche]
    if min_followers is not None:
        try:
            mf = int(min_followers)
        except ValueError:
            raise err.validation("min_followers must be an integer")
        items = [c for c in items if c["followers"] >= mf]
    return resp.paginate(items, request.args)


@bp.route("/creators/<cid>", methods=["GET"])
@require_roles("TalentManager", "BrandManager", "FinanceAdmin",
               "ComplianceOfficer", "Creator")
def get_creator(actor, cid):
    creator = H.get_or_404(db.creators, cid, "creator")
    if actor.role == "Creator":
        require_owner(actor, creator["id"], "creator")
    return resp.ok(creator)


@bp.route("/creators/<cid>/metrics", methods=["PATCH"])
@require_roles("TalentManager")
def update_metrics(actor, cid):
    creator = H.get_or_404(db.creators, cid, "creator")
    payload = H.body()
    followers = H.require_int(payload, "followers", minimum=0)
    avg_views = H.require_int(payload, "avg_views_30d", minimum=0)
    eng_bps = H.require_int(payload, "engagement_rate_bps", minimum=0)

    creator["followers"] = followers
    creator["avg_views_30d"] = avg_views
    creator["engagement_rate_bps"] = eng_bps
    cpm, flat = calc.rate_card(followers, eng_bps, creator["niche"], avg_views)
    creator["rate_card_cpm_cents"] = cpm
    creator["rate_card_flat_cents"] = flat
    H.touch(creator)
    return resp.ok(creator)


@bp.route("/creators/<cid>/transition", methods=["POST"])
@require_roles("TalentManager")
def transition_creator(actor, cid):
    creator = H.get_or_404(db.creators, cid, "creator")
    payload = H.body()
    H.req_fields(payload, ["to_state"])
    to_state = H.require_enum(payload, "to_state", H.CREATOR_STATUS_ENUM)

    current = creator["status"]
    if current == "EXITED":
        raise err.already_terminal("Creator is EXITED")

    allowed = {
        ("APPLIED", "SCREENING"),
        ("SCREENING", "ACTIVE"),
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "EXITED"),
        ("SUSPENDED", "EXITED"),
    }
    if (current, to_state) not in allowed:
        raise err.invalid_state(
            f"Creator cannot transition {current} -> {to_state}")

    if to_state == "EXITED":
        # Business rule: no non-terminal deals (ERR_ACTIVE_DEALS_EXIST).
        for deal in db.deals.values():
            if deal["creator_id"] == cid and deal["status"] not in (
                    "COMPLETED", "TERMINATED"):
                raise err.ApiError(
                    err.ERR_ACTIVE_DEALS_EXIST,
                    "Creator has non-terminal deals", 422)

    if current == "SCREENING" and to_state == "ACTIVE":
        cpm, flat = calc.rate_card(creator["followers"],
                                   creator["engagement_rate_bps"],
                                   creator["niche"],
                                   creator["avg_views_30d"])
        creator["rate_card_cpm_cents"] = cpm
        creator["rate_card_flat_cents"] = flat
        creator["status"] = "ACTIVE"
        H.touch(creator)
    elif to_state == "SUSPENDED":
        lifecycle.suspend_creator(creator)
    elif current == "SUSPENDED" and to_state == "ACTIVE":
        creator["compliance_strikes"] = 0
        creator["status"] = "ACTIVE"
        H.touch(creator)
    else:
        creator["status"] = to_state
        H.touch(creator)

    return resp.ok(creator)
