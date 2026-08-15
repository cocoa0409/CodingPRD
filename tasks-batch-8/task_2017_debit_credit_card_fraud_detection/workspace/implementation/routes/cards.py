"""Card endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("cards", __name__)

VALID_PRODUCT = {"DEBIT", "CREDIT"}
VALID_NETWORK = {"VISA", "MASTERCARD"}
VALID_BLOCK_TYPE = {"SOFT", "HARD"}
VALID_BLOCK_REASON = {"ANALYST_REVIEW", "CONFIRMED_FRAUD", "CUSTOMER_REQUEST", "COMPROMISE_EVENT"}


@bp.route("/fraudops/cards", methods=["POST"])
def create_card():
    middleware.require_role("FraudOpsManager")
    body = request.get_json(silent=True) or {}
    account_id = body.get("account_id")
    pan_token = body.get("pan_token")
    product_type = body.get("product_type")
    network = body.get("network")

    if not isinstance(account_id, str) or not account_id:
        raise errors.err_invalid_request("account_id is required")
    if not isinstance(pan_token, str) or not pan_token:
        raise errors.err_invalid_request("pan_token is required")
    if product_type not in VALID_PRODUCT:
        raise errors.err_invalid_request("product_type must be DEBIT or CREDIT")
    if network not in VALID_NETWORK:
        raise errors.err_invalid_request("network must be VISA or MASTERCARD")

    acct = db.accounts.get(account_id)
    if not acct:
        raise errors.err_not_found("Account not found")

    for c in db.cards.values():
        if c["pan_token"] == pan_token:
            raise errors.err_invalid_request("pan_token already exists")

    if acct["account_status"] != "ACTIVE":
        raise errors.err_account_not_active()

    rec = middleware.stamp_new(
        {
            "account_id": account_id,
            "pan_token": pan_token,
            "product_type": product_type,
            "network": network,
            "card_status": "ACTIVE",
            "fraud_flag": "CLEAN",
            "block_reason": None,
            "replaces_card_id": None,
        }
    )
    db.cards[rec["id"]] = rec
    return response.success(domain.ser_card(rec), status_code=201)


@bp.route("/fraudops/cards", methods=["GET"])
def list_cards():
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    args = request.args
    items = sorted(db.cards.values(), key=lambda c: (c["created_at"], c["id"]))
    for key in ("account_id", "replaces_card_id", "card_status", "fraud_flag"):
        v = args.get(key)
        if v:
            items = [c for c in items if c.get(key) == v]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_card(c) for c in sliced], pagination=pg)


@bp.route("/fraudops/cards/<cid>", methods=["GET"])
def get_card(cid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    c = db.cards.get(cid)
    if not c:
        raise errors.err_not_found("Card not found")
    return response.success(domain.ser_card(c))


@bp.route("/fraudops/cards/<cid>/block", methods=["POST"])
def block_card(cid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    c = db.cards.get(cid)
    if not c:
        raise errors.err_not_found("Card not found")
    body = request.get_json(silent=True) or {}
    block_type = body.get("block_type")
    reason = body.get("reason")
    if block_type not in VALID_BLOCK_TYPE:
        raise errors.err_invalid_request("block_type must be SOFT or HARD")
    if reason not in VALID_BLOCK_REASON:
        raise errors.err_invalid_request("reason must be a valid block_reason enum")

    if block_type == "SOFT":
        if c["card_status"] != "ACTIVE":
            raise errors.err_invalid_state("Card is not ACTIVE")
        c["card_status"] = "SOFT_BLOCKED"
        c["block_reason"] = reason
    else:  # HARD
        if c["card_status"] not in ("ACTIVE", "SOFT_BLOCKED"):
            raise errors.err_invalid_state("Card cannot be hard-blocked from its current state")
        c["card_status"] = "HARD_CLOSED"
        c["block_reason"] = reason
    middleware.touch(c)
    return response.success(domain.ser_card(c))


@bp.route("/fraudops/cards/<cid>/unblock", methods=["POST"])
def unblock_card(cid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager")
    c = db.cards.get(cid)
    if not c:
        raise errors.err_not_found("Card not found")
    if c["card_status"] != "SOFT_BLOCKED":
        raise errors.err_invalid_state("Card is not SOFT_BLOCKED")
    # compromise rule
    if c["fraud_flag"] == "COMPROMISED":
        declined = any(
            d["card_id"] == cid and d["decision"] == "DECLINED"
            for d in db.reissue_decisions.values()
        )
        if not declined:
            raise errors.err_card_compromised()
    c["card_status"] = "ACTIVE"
    c["block_reason"] = None
    middleware.touch(c)
    return response.success(domain.ser_card(c))


@bp.route("/fraudops/cards/<cid>/travel-notices", methods=["GET"])
def list_card_travel_notices(cid):
    user_id, role = middleware.require_role("FraudAnalyst", "FraudOpsManager", "Cardholder")
    c = db.cards.get(cid)
    if not c:
        raise errors.err_not_found("Card not found")
    if role == "Cardholder" and user_id != c["account_id"]:
        raise errors.err_not_resource_owner()
    args = request.args
    items = [n for n in db.travel_notices.values() if n["card_id"] == cid]
    # lazy expiry
    for n in items:
        domain._apply_travel_notice_expiry(n)
    items = sorted(items, key=lambda n: (n["created_at"], n["id"]))
    ns = args.get("notice_status")
    if ns:
        items = [n for n in items if n["notice_status"] == ns]
    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_notice(n) for n in sliced], pagination=pg)
