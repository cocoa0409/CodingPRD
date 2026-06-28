"""Referral endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.ledger import emit_ledger
from services.serialize import referral_out
from state import store
from validation import get_json_body, require_string, optional_int

bp = Blueprint("referrals", __name__)


@bp.route("/referrals", methods=["POST"])
def create_referral():
    user_id, role = get_identity()
    require_roles(role, ["Member", "PlatformAdmin"])
    body = get_json_body()

    referrer_member_id = body.get("referrer_member_id")
    if referrer_member_id is None:
        raise err("ERR_VALIDATION", "Missing required field: referrer_member_id")
    if not isinstance(referrer_member_id, str) or referrer_member_id not in store.members:
        raise err("ERR_REFERENCE_NOT_FOUND", "referrer_member_id does not resolve.")

    referee_email = require_string(body, "referee_email")
    referee_qualifying_cents = optional_int(body, "referee_qualifying_cents", 1000, minimum=0)
    bonus_cents = optional_int(body, "bonus_cents", 500, minimum=0)

    if role == "Member" and not member_owns(user_id, referrer_member_id):
        raise err("ERR_FORBIDDEN", "A member may only send referrals as themselves.")

    # Duplicate guard: no referral for this email already past INVITED.
    for r in store.referrals.values():
        if r["referee_email"] == referee_email and r["status"] in (
            "SIGNED_UP", "QUALIFIED", "REWARDED"
        ):
            raise err("ERR_DUPLICATE_REFERRAL",
                      "A referral for this email already exists past invited.")

    r = base_common_fields(store, full=True)
    r.update({
        "referrer_member_id": referrer_member_id,
        "referee_email": referee_email,
        "referee_member_id": None,
        "referee_qualifying_cents": referee_qualifying_cents,
        "bonus_cents": bonus_cents,
        "status": "INVITED",
    })
    store.referrals[r["id"]] = r
    return object_response(store.clock, referral_out(store, r), status=201)


@bp.route("/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    r = store.referrals.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Referral not found.")
    if role == "Member":
        owns = member_owns(user_id, r["referrer_member_id"]) or (
            r.get("referee_member_id") is not None
            and member_owns(user_id, r["referee_member_id"])
        )
        if not owns:
            raise err("ERR_FORBIDDEN", "A member may only read their own referrals.")
    return object_response(store.clock, referral_out(store, r))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    user_id, role = get_identity()
    require_roles(role, ["PlatformAdmin", "FinanceAdmin", "Member"])
    items = list(store.referrals.values())
    if role == "Member":
        items = [
            r for r in items
            if r["referrer_member_id"] == user_id
            or r.get("referee_member_id") == user_id
        ]
    referrer = request.args.get("referrer_member_id")
    referee = request.args.get("referee_member_id")
    status = request.args.get("status")
    if referrer is not None:
        items = [r for r in items if r["referrer_member_id"] == referrer]
    if referee is not None:
        items = [r for r in items if r.get("referee_member_id") == referee]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, referral_out)


@bp.route("/referrals/<rid>/reward", methods=["POST"])
def reward_referral(rid):
    _, role = get_identity()
    require_roles(role, ["FinanceAdmin"])
    r = store.referrals.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Referral not found.")
    if r["status"] != "QUALIFIED":
        raise err("ERR_REFERRAL_NOT_QUALIFIED", "Referral is not QUALIFIED.")

    referrer_id = r["referrer_member_id"]
    referrer = store.members.get(referrer_id)
    merchant_id = None  # referral bonus is not merchant-bound

    # CASCADE step 1: create an AVAILABLE ONLINE claim for the referrer.
    claim = base_common_fields(store, full=True)
    claim.update({
        "member_id": referrer_id,
        "merchant_id": merchant_id,
        "offer_id": None,
        "click_through_id": None,
        "receipt_scan_id": None,
        "attribution": "ONLINE",
        "purchase_amount_cents": 0,
        "amount_cents": r["bonus_cents"],
        "status": "AVAILABLE",
        "matures_at": claim_created_now(),
        "expires_at": None,
        "cashout_id": None,
        "_matured_week_index": None,
    })
    store.reward_claims[claim["id"]] = claim

    # CASCADE step 2: REFERRAL_BONUS ledger entry (+bonus_cents).
    emit_ledger(store, referrer_id, "REFERRAL_BONUS", r["bonus_cents"],
                reward_claim_id=claim["id"], referral_id=r["id"])

    # CASCADE step 3: referrer available balance rises by bonus_cents (derived).
    r["status"] = "REWARDED"
    touch(store, r)
    return object_response(store.clock, referral_out(store, r))


def claim_created_now():
    from clock import format_iso
    return format_iso(store.clock.get())
