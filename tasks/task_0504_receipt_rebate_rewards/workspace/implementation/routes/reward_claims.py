"""RewardClaim endpoints (PRD §3.3, §3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import parse_iso, format_iso
from constants import AVAILABLE_EXPIRY_DAYS
from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.calculations import compute_online_reward
from services.claims import mature_claim
from services.ledger import emit_ledger
from services.serialize import reward_claim_out
from state import store
from validation import get_json_body, require_int

bp = Blueprint("reward_claims", __name__)

ALL_ROLES = ["PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"]


def _offer_active(offer):
    if offer["status"] != "ACTIVE":
        return False
    now = store.clock.get()
    starts = parse_iso(offer["starts_at"])
    expires = parse_iso(offer["expires_at"])
    if starts is None or expires is None:
        return False
    return starts <= now <= expires


def _claim_windows(created_at_iso, maturity_hold_days):
    created = parse_iso(created_at_iso)
    matures = created + timedelta(days=maturity_hold_days)
    expires = matures + timedelta(days=AVAILABLE_EXPIRY_DAYS)
    return format_iso(matures), format_iso(expires)


@bp.route("/reward-claims", methods=["POST"])
def create_reward_claim():
    user_id, role = get_identity()
    require_roles(role, ["Member", "PlatformAdmin"])
    body = get_json_body()

    member_id = body.get("member_id")
    merchant_id = body.get("merchant_id")
    click_through_id = body.get("click_through_id")
    offer_id = body.get("offer_id")

    for field in ("member_id", "merchant_id", "click_through_id"):
        if body.get(field) is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)

    # Body-FK resolution (priority 4).
    if not isinstance(member_id, str) or member_id not in store.members:
        raise err("ERR_REFERENCE_NOT_FOUND", "member_id does not resolve.")
    if not isinstance(merchant_id, str) or merchant_id not in store.merchants:
        raise err("ERR_REFERENCE_NOT_FOUND", "merchant_id does not resolve.")
    if not isinstance(click_through_id, str) or click_through_id not in store.clickthroughs:
        raise err("ERR_REFERENCE_NOT_FOUND", "click_through_id does not resolve.")
    if offer_id is not None:
        if not isinstance(offer_id, str) or offer_id not in store.offers:
            raise err("ERR_REFERENCE_NOT_FOUND", "offer_id does not resolve.")

    # Shape (priority 5).
    purchase_amount_cents = require_int(body, "purchase_amount_cents", minimum=0)

    if role == "Member" and not member_owns(user_id, member_id):
        raise err("ERR_FORBIDDEN", "A member may only act on their own member_id.")

    merchant = store.merchants[merchant_id]
    if merchant["status"] == "DISABLED":
        raise err("ERR_MERCHANT_DISABLED", "Merchant is disabled.")

    offer = store.offers.get(offer_id) if offer_id is not None else None

    # Offer-active (priority 8) when an offer is supplied.
    if offer is not None and not _offer_active(offer):
        raise err("ERR_OFFER_INACTIVE", "Offer is not active.")

    # Attribution window (priority 10): a qualifying ClickThrough must exist for
    # member+merchant with clicked_at within attribution_window_hours before the
    # claim (current clock).
    if not _has_qualifying_click(member_id, merchant_id, merchant["attribution_window_hours"]):
        raise err("ERR_ATTRIBUTION_WINDOW_EXPIRED",
                  "No qualifying click-through within the attribution window.")

    amount = compute_online_reward(purchase_amount_cents, merchant, offer)

    claim = base_common_fields(store, full=True)
    matures_at, expires_at = _claim_windows(claim["created_at"], merchant["maturity_hold_days"])
    claim.update({
        "member_id": member_id,
        "merchant_id": merchant_id,
        "offer_id": offer_id,
        "click_through_id": click_through_id,
        "receipt_scan_id": None,
        "attribution": "ONLINE",
        "purchase_amount_cents": purchase_amount_cents,
        "amount_cents": amount,
        "status": "PENDING",
        "matures_at": matures_at,
        "expires_at": expires_at,
        "cashout_id": None,
        "_matured_week_index": None,
    })
    store.reward_claims[claim["id"]] = claim

    emit_ledger(store, member_id, "CLAIM_PENDING", claim["amount_cents"],
                reward_claim_id=claim["id"])

    return object_response(store.clock, reward_claim_out(store, claim), status=201)


def _has_qualifying_click(member_id, merchant_id, window_hours):
    now = store.clock.get()
    window = timedelta(hours=window_hours)
    for ct in store.clickthroughs.values():
        if ct["member_id"] != member_id or ct["merchant_id"] != merchant_id:
            continue
        clicked = parse_iso(ct["clicked_at"])
        if clicked is None:
            continue
        # clicked within the window before now (inclusive); click must not be in
        # the future relative to the claim.
        if clicked <= now and (now - clicked) <= window:
            return True
    return False


@bp.route("/reward-claims/<cid>", methods=["GET"])
def get_reward_claim(cid):
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    c = store.reward_claims.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Reward claim not found.")
    if role == "Member" and not member_owns(user_id, c["member_id"]):
        raise err("ERR_FORBIDDEN", "A member may only read their own reward claims.")
    return object_response(store.clock, reward_claim_out(store, c))


@bp.route("/reward-claims", methods=["GET"])
def list_reward_claims():
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    items = list(store.reward_claims.values())
    if role == "Member":
        items = [c for c in items if c["member_id"] == user_id]
    for field in ("member_id", "merchant_id", "offer_id", "click_through_id",
                  "receipt_scan_id", "cashout_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    return list_response(items, reward_claim_out)


@bp.route("/reward-claims/<cid>/mature", methods=["POST"])
def force_mature(cid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    c = store.reward_claims.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND", "Reward claim not found.")
    if c["status"] in ("PAID", "CLAWED_BACK", "EXPIRED"):
        raise err("ERR_CLAIM_ALREADY_TERMINAL", "Claim is already terminal.")
    if c["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING claim may be matured.")
    matures = parse_iso(c["matures_at"])
    if matures is None or store.clock.get() < matures:
        raise err("ERR_INVALID_STATE", "Claim has not reached its maturation instant.")
    mature_claim(store, c)
    return object_response(store.clock, reward_claim_out(store, c))
