from flask import Blueprint, request

from db import db, base_fields, bump
from middleware import get_auth, require_role
from validators import get_body, req_str, req_int, opt_int
from errors import err
from response import success
from pagination import paginate
import serializers as S
import services as svc
import calculations as calc

bp = Blueprint("offers", __name__)


def _opposite(side):
    return "CREATOR" if side == "BRAND" else "BRAND"


def _acting_side(role):
    return "BRAND" if role == "Brand" else "CREATOR"


def _check_offer_owner(offer, user_id, role):
    """Ownership for offer actions (PRD 2.1).

    Brand owns the offer by owning the underlying campaign; Creator owns its side
    of the offer via creator_id."""
    if role == "Brand":
        camp = db.campaigns.get(offer["campaign_id"])
        if not camp or camp["brand_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this offer's campaign")
    elif role == "Creator":
        if offer["creator_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER", "Acting creator does not own this offer")


@bp.route("/offers", methods=["POST"])
def create_offer():
    user_id, role = get_auth()
    require_role(role, {"Brand", "Creator"})
    body = get_body()
    campaign_id = req_str(body, "campaign_id", allow_empty=False)
    creator_id = req_str(body, "creator_id", allow_empty=False)
    current_amount_cents = req_int(body, "current_amount_cents", minimum=1)
    exclusivity_days = opt_int(body, "exclusivity_days", default=0, minimum=0)

    # existence (priority 4)
    campaign = svc.get_campaign(campaign_id)
    creator = svc.get_creator(creator_id)

    # ownership for the initiating side
    if role == "Brand" and campaign["brand_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting brand does not own this campaign")
    if role == "Creator" and creator_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting creator must open offers for itself")

    # parent campaign must be OPEN (state)
    if campaign["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Offers can only be opened on an OPEN campaign")

    initiated_by = _acting_side(role)
    rec = base_fields()
    rec.update({
        "campaign_id": campaign_id,
        "creator_id": creator_id,
        "initiated_by": initiated_by,
        "current_amount_cents": current_amount_cents,
        "last_actor": initiated_by,
        "round_count": 0,
        "exclusivity_days": exclusivity_days,
        "status": "OFFERED",
    })
    db.offers[rec["id"]] = rec
    return success(S.offer_view(rec), status=201)


@bp.route("/offers/<offer_id>", methods=["GET"])
def get_offer(offer_id):
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    o = svc.get_offer(offer_id)
    return success(S.offer_view(o), status=200)


@bp.route("/offers", methods=["GET"])
def list_offers():
    _, role = get_auth()
    require_role(role, {"PlatformAdmin", "Brand", "Creator", "ComplianceOfficer"})
    campaign_id = request.args.get("campaign_id")
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    rows = list(db.offers.values())
    if campaign_id is not None:
        rows = [o for o in rows if o["campaign_id"] == campaign_id]
    if creator_id is not None:
        rows = [o for o in rows if o["creator_id"] == creator_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    page, meta = paginate(rows)
    return success([S.offer_view(o) for o in page], status=200, pagination=meta)


def _check_offer_version(offer, body):
    expected = body.get("expected_offer_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_offer_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_offer_version must be an integer")
    if expected != offer["version"]:
        raise err("ERR_STALE_OFFER_VERSION", "expected_offer_version does not match offer.version")


@bp.route("/offers/<offer_id>/counter", methods=["POST"])
def counter_offer(offer_id):
    user_id, role = get_auth()
    require_role(role, {"Brand", "Creator"})
    o = svc.get_offer(offer_id)
    _check_offer_owner(o, user_id, role)
    body = get_body()
    counter_amount = req_int(body, "counter_amount_cents", minimum=1)
    # version field shape validated as part of body (priority 5); OCC checked later
    if "expected_offer_version" not in body or body["expected_offer_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_offer_version")
    if not isinstance(body["expected_offer_version"], int) or isinstance(body["expected_offer_version"], bool):
        raise err("ERR_INVALID_REQUEST", "expected_offer_version must be an integer")

    # state legality (priority 7): counter from OFFERED or COUNTERED
    if o["status"] not in {"OFFERED", "COUNTERED"}:
        raise err("ERR_INVALID_STATE", "Offer is not in a counterable state")

    # OCC (priority 8)
    if body["expected_offer_version"] != o["version"]:
        raise err("ERR_STALE_OFFER_VERSION", "expected_offer_version does not match offer.version")

    # wrong turn (priority 9): must come from side opposite last_actor
    acting = _acting_side(role)
    if acting == o["last_actor"]:
        raise err("ERR_WRONG_TURN", "It is not your turn to act")

    # round cap (priority 10)
    if o["round_count"] >= calc.MAX_NEGOTIATION_ROUNDS:
        raise err("ERR_NEGOTIATION_ROUND_CAP", "Negotiation round cap reached")

    # parent campaign must still be OPEN (business)
    campaign = db.campaigns.get(o["campaign_id"])
    if not campaign or campaign["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Parent campaign is not OPEN")

    o["current_amount_cents"] = counter_amount
    o["last_actor"] = acting
    o["round_count"] += 1
    o["status"] = "COUNTERED"
    bump(o)
    return success(S.offer_view(o), status=200)


@bp.route("/offers/<offer_id>/accept", methods=["POST"])
def accept_offer(offer_id):
    user_id, role = get_auth()
    require_role(role, {"Brand", "Creator"})
    o = svc.get_offer(offer_id)
    _check_offer_owner(o, user_id, role)
    body = get_body()
    if "expected_offer_version" not in body or body["expected_offer_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_offer_version")
    if not isinstance(body["expected_offer_version"], int) or isinstance(body["expected_offer_version"], bool):
        raise err("ERR_INVALID_REQUEST", "expected_offer_version must be an integer")

    if o["status"] not in {"OFFERED", "COUNTERED"}:
        raise err("ERR_INVALID_STATE", "Offer is not in an acceptable state")

    if body["expected_offer_version"] != o["version"]:
        raise err("ERR_STALE_OFFER_VERSION", "expected_offer_version does not match offer.version")

    acting = _acting_side(role)
    if acting == o["last_actor"]:
        raise err("ERR_WRONG_TURN", "It is not your turn to act")

    campaign = db.campaigns.get(o["campaign_id"])
    if not campaign or campaign["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Parent campaign is not OPEN")

    o["status"] = "ACCEPTED"
    bump(o)
    return success(S.offer_view(o), status=200)


@bp.route("/offers/<offer_id>/decline", methods=["POST"])
def decline_offer(offer_id):
    user_id, role = get_auth()
    require_role(role, {"Brand", "Creator"})
    o = svc.get_offer(offer_id)
    _check_offer_owner(o, user_id, role)

    # decline carries no version field and no campaign-state precondition (PRD 3.4)
    if o["status"] not in {"OFFERED", "COUNTERED"}:
        raise err("ERR_INVALID_STATE", "Offer is not in a declinable state")

    acting = _acting_side(role)
    if acting == o["last_actor"]:
        raise err("ERR_WRONG_TURN", "It is not your turn to act")

    o["status"] = "DECLINED"
    bump(o)
    return success(S.offer_view(o), status=200)
