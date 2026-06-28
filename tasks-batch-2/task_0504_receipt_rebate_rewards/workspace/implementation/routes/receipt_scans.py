"""ReceiptScan endpoints (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

from clock import parse_iso
from constants import DOUBLE_DIP_WINDOW_HOURS
from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response, member_owns
from services.calculations import compute_instore_reward
from services.claims import maybe_qualify_referrals_for
from services.ledger import emit_ledger
from services.serialize import receipt_scan_out
from state import store
from validation import get_json_body, require_int, require_string

bp = Blueprint("receipt_scans", __name__)

ALL_ROLES = ["PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"]


def _offer_active(offer):
    """Offer ACTIVE and current clock within [starts_at, expires_at] inclusive."""
    if offer["status"] != "ACTIVE":
        return False
    now = store.clock.get()
    starts = parse_iso(offer["starts_at"])
    expires = parse_iso(offer["expires_at"])
    if starts is None or expires is None:
        return False
    return starts <= now <= expires


@bp.route("/receipt-scans", methods=["POST"])
def create_receipt_scan():
    user_id, role = get_identity()
    require_roles(role, ["Member", "PlatformAdmin"])
    body = get_json_body()

    member_id = body.get("member_id")
    merchant_id = body.get("merchant_id")
    offer_id = body.get("offer_id")

    for field in ("member_id", "merchant_id", "offer_id"):
        if body.get(field) is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % field)

    if not isinstance(member_id, str) or member_id not in store.members:
        raise err("ERR_REFERENCE_NOT_FOUND", "member_id does not resolve.")
    if not isinstance(merchant_id, str) or merchant_id not in store.merchants:
        raise err("ERR_REFERENCE_NOT_FOUND", "merchant_id does not resolve.")
    if not isinstance(offer_id, str) or offer_id not in store.offers:
        raise err("ERR_REFERENCE_NOT_FOUND", "offer_id does not resolve.")

    purchase_total_cents = require_int(body, "purchase_total_cents", minimum=0)
    purchased_at = require_string(body, "purchased_at")
    if parse_iso(purchased_at) is None:
        raise err("ERR_VALIDATION", "purchased_at must be an ISO 8601 instant.")

    if role == "Member" and not member_owns(user_id, member_id):
        raise err("ERR_FORBIDDEN", "A member may only act on their own member_id.")

    merchant = store.merchants[merchant_id]
    if merchant["status"] == "DISABLED":
        raise err("ERR_MERCHANT_DISABLED", "Merchant is disabled.")

    r = base_common_fields(store, full=True)
    r.update({
        "member_id": member_id,
        "merchant_id": merchant_id,
        "offer_id": offer_id,
        "purchase_total_cents": purchase_total_cents,
        "purchased_at": purchased_at,
        "status": "SUBMITTED",
        "review_note": None,
        "reward_claim_id": None,
    })
    store.receipt_scans[r["id"]] = r
    return object_response(store.clock, receipt_scan_out(store, r), status=201)


@bp.route("/receipt-scans/<rid>", methods=["GET"])
def get_receipt_scan(rid):
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    r = store.receipt_scans.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Receipt scan not found.")
    if role == "Member" and not member_owns(user_id, r["member_id"]):
        raise err("ERR_FORBIDDEN", "A member may only read their own receipt scans.")
    return object_response(store.clock, receipt_scan_out(store, r))


@bp.route("/receipt-scans", methods=["GET"])
def list_receipt_scans():
    user_id, role = get_identity()
    require_roles(role, ALL_ROLES)
    items = list(store.receipt_scans.values())
    if role == "Member":
        items = [r for r in items if r["member_id"] == user_id]
    member_id = request.args.get("member_id")
    merchant_id = request.args.get("merchant_id")
    offer_id = request.args.get("offer_id")
    reward_claim_id = request.args.get("reward_claim_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if merchant_id is not None:
        items = [r for r in items if r["merchant_id"] == merchant_id]
    if offer_id is not None:
        items = [r for r in items if r["offer_id"] == offer_id]
    if reward_claim_id is not None:
        items = [r for r in items if r.get("reward_claim_id") == reward_claim_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, receipt_scan_out)


@bp.route("/receipt-scans/<rid>/start-review", methods=["POST"])
def start_review(rid):
    _, role = get_identity()
    require_roles(role, ["ReviewAgent"])
    r = store.receipt_scans.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Receipt scan not found.")
    if r["status"] not in ("SUBMITTED", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Receipt is not in a reviewable state.")
    offer = store.offers.get(r["offer_id"])
    if offer is None or not _offer_active(offer):
        raise err("ERR_OFFER_INACTIVE", "Offer is not active.")
    r["status"] = "IN_REVIEW"
    touch(store, r)
    return object_response(store.clock, receipt_scan_out(store, r))


@bp.route("/receipt-scans/<rid>/reject", methods=["POST"])
def reject_receipt(rid):
    _, role = get_identity()
    require_roles(role, ["ReviewAgent"])
    r = store.receipt_scans.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Receipt scan not found.")
    body = get_json_body()
    if r["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Receipt is not in review.")
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise err("ERR_VALIDATION", "review_note must be a string.")
    r["status"] = "REJECTED"
    if review_note is not None:
        r["review_note"] = review_note
    touch(store, r)
    return object_response(store.clock, receipt_scan_out(store, r))


@bp.route("/receipt-scans/<rid>/approve", methods=["POST"])
def approve_receipt(rid):
    _, role = get_identity()
    require_roles(role, ["ReviewAgent"])
    r = store.receipt_scans.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "Receipt scan not found.")
    body = get_json_body()
    if r["status"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Receipt is not in review.")

    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise err("ERR_VALIDATION", "review_note must be a string.")

    offer = store.offers.get(r["offer_id"])
    merchant = store.merchants.get(r["merchant_id"])
    member = store.members.get(r["member_id"])

    # Offer-active precondition also applies at approve (validation priority 8).
    if offer is None or not _offer_active(offer):
        raise err("ERR_OFFER_INACTIVE", "Offer is not active.")

    # Approval preconditions, in order (PRD §3.4):
    # 1. min spend
    if r["purchase_total_cents"] < offer["min_spend_cents"]:
        raise err("ERR_MIN_SPEND_NOT_MET", "Purchase total below offer minimum spend.")
    # 2. member active
    if member is None or member["account_status"] != "ACTIVE":
        raise err("ERR_MEMBER_SUSPENDED", "Member is suspended.")
    # 3. double-dip (when merchant.double_dip_allowed == false)
    if not merchant["double_dip_allowed"]:
        if _has_conflicting_online_claim(member["id"], merchant["id"], r["purchased_at"]):
            raise err("ERR_DOUBLE_DIP_BLOCKED", "Double-dip is not allowed for this merchant.")

    # All preconditions pass — cascade.
    amount = compute_instore_reward(r["purchase_total_cents"], merchant, offer)

    claim = base_common_fields(store, full=True)
    matures_at, expires_at = _claim_windows(claim["created_at"], merchant["maturity_hold_days"])
    claim.update({
        "member_id": member["id"],
        "merchant_id": merchant["id"],
        "offer_id": offer["id"],
        "click_through_id": None,
        "receipt_scan_id": r["id"],
        "attribution": "IN_STORE",
        "purchase_amount_cents": r["purchase_total_cents"],
        "amount_cents": amount,
        "status": "PENDING",
        "matures_at": matures_at,
        "expires_at": expires_at,
        "cashout_id": None,
        "_matured_week_index": None,
    })
    store.reward_claims[claim["id"]] = claim

    emit_ledger(store, member["id"], "CLAIM_PENDING", claim["amount_cents"],
                reward_claim_id=claim["id"])

    r["status"] = "APPROVED"
    r["reward_claim_id"] = claim["id"]
    if review_note is not None:
        r["review_note"] = review_note
    touch(store, r)

    return object_response(store.clock, receipt_scan_out(store, r))


def _claim_windows(created_at_iso, maturity_hold_days):
    from constants import AVAILABLE_EXPIRY_DAYS
    created = parse_iso(created_at_iso)
    matures = created + timedelta(days=maturity_hold_days)
    expires = matures + timedelta(days=AVAILABLE_EXPIRY_DAYS)
    from clock import format_iso
    return format_iso(matures), format_iso(expires)


def _has_conflicting_online_claim(member_id, merchant_id, purchased_at_iso):
    """No existing non-clawed RewardClaim with ONLINE attribution for the same
    member+merchant whose ClickThrough.clicked_at is within
    DOUBLE_DIP_WINDOW_HOURS of the receipt's purchased_at."""
    purchased = parse_iso(purchased_at_iso)
    if purchased is None:
        return False
    window = timedelta(hours=DOUBLE_DIP_WINDOW_HOURS)
    for c in store.reward_claims.values():
        if c["member_id"] != member_id or c["merchant_id"] != merchant_id:
            continue
        if c["attribution"] != "ONLINE":
            continue
        if c["status"] == "CLAWED_BACK":
            continue
        ct_id = c.get("click_through_id")
        if ct_id is None:
            continue
        ct = store.clickthroughs.get(ct_id)
        if ct is None:
            continue
        clicked = parse_iso(ct["clicked_at"])
        if clicked is None:
            continue
        if abs((clicked - purchased).total_seconds()) <= window.total_seconds():
            return True
    return False
