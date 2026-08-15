"""AuthTransaction endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
from services import domain

bp = Blueprint("auth_transactions", __name__)

VALID_CHANNELS = {"CHIP", "CONTACTLESS", "CNP", "ATM"}


@bp.route("/fraudops/auth-transactions", methods=["POST"])
def create_txn():
    middleware.require_role("NetworkGateway")
    body = request.get_json(silent=True) or {}
    card_id = body.get("card_id")
    amount_cents = body.get("amount_cents")
    merchant_id = body.get("merchant_id")
    mcc = body.get("merchant_category_code")
    channel = body.get("channel")
    origin_country = body.get("origin_country")
    currency = body.get("currency", "USD")

    if not isinstance(card_id, str) or not card_id:
        raise errors.err_invalid_request("card_id is required")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < 1:
        raise errors.err_invalid_request("amount_cents must be >= 1")
    if not isinstance(merchant_id, str) or not merchant_id:
        raise errors.err_invalid_request("merchant_id is required")
    if not isinstance(mcc, str) or not mcc:
        raise errors.err_invalid_request("merchant_category_code is required")
    if channel not in VALID_CHANNELS:
        raise errors.err_invalid_request("channel must be one of CHIP, CONTACTLESS, CNP, ATM")
    if not isinstance(origin_country, str) or not origin_country:
        raise errors.err_invalid_request("origin_country is required")
    if not isinstance(currency, str):
        raise errors.err_invalid_request("currency must be a string")

    card = db.cards.get(card_id)
    if not card:
        raise errors.err_not_found("Card not found")
    account = db.accounts[card["account_id"]]
    scored_at_iso = db.get_clock_iso()

    txn = {
        "card_id": card_id,
        "account_id": account["id"],
        "ruleset_id": None,
        "amount_cents": amount_cents,
        "currency": currency,
        "merchant_id": merchant_id,
        "merchant_category_code": mcc,
        "channel": channel,
        "origin_country": origin_country,
        "home_country": account["home_country"],
        "scored_at": scored_at_iso,
        "auth_score": None,
        "decision": None,
        "decision_reason": None,
        "shadow_score": None,
        "shadow_decision": None,
        "shadow_ruleset_id": None,
        "final_disposition": "UNDISPOSED",
    }

    if card["card_status"] != "ACTIVE":
        txn["decision"] = "DECLINE"
        txn["decision_reason"] = "CARD_BLOCKED"
        txn["auth_score"] = None
        txn["ruleset_id"] = None
    else:
        ruleset = domain.resolve_scoring_ruleset(card["product_type"])
        if not ruleset:
            raise errors.err_no_active_ruleset()
        score = domain.compute_score(
            card, account, ruleset, amount_cents, channel, origin_country, scored_at_iso
        )
        decision = domain.score_decision(ruleset, score)
        txn["decision"] = decision
        txn["decision_reason"] = "RULE_SCORE"
        txn["auth_score"] = score
        txn["ruleset_id"] = ruleset["id"]

    middleware.stamp_new(txn)
    db.auth_transactions[txn["id"]] = txn

    # Create a SCORING_REVIEW alert on REVIEW
    if txn["decision"] == "REVIEW" and txn["decision_reason"] == "RULE_SCORE":
        ruleset = db.rule_sets[txn["ruleset_id"]]
        band = max(0, txn["auth_score"] - ruleset["review_threshold"])
        if band > 49:
            band = 49
        domain.create_alert(
            account_id=account["id"],
            card_id=card_id,
            auth_transaction_id=txn["id"],
            source="SCORING_REVIEW",
            band_points=band,
        )

    return response.success(domain.ser_txn(txn), status_code=201)


@bp.route("/fraudops/auth-transactions", methods=["GET"])
def list_txns():
    middleware.require_role("FraudAnalyst", "FraudOpsManager", "RecoverySpecialist")
    args = request.args
    items = sorted(db.auth_transactions.values(), key=lambda t: (t["created_at"], t["id"]))

    for key in ("card_id", "account_id", "ruleset_id", "decision", "final_disposition", "merchant_id"):
        v = args.get(key)
        if v:
            items = [t for t in items if t.get(key) == v]

    # shadow_ruleset_id requires read-time computation
    shadow_rs = args.get("shadow_ruleset_id")
    if shadow_rs:
        filtered = []
        for t in items:
            domain.apply_shadow(t)
            if t.get("shadow_ruleset_id") == shadow_rs:
                filtered.append(t)
        items = filtered
    else:
        for t in items:
            domain.apply_shadow(t)

    limit, offset = domain.parse_pagination_args(args)
    sliced, pg = domain.paginate(items, limit, offset)
    return response.success([domain.ser_txn(t) for t in sliced], pagination=pg)


@bp.route("/fraudops/auth-transactions/<tid>", methods=["GET"])
def get_txn(tid):
    middleware.require_role("FraudAnalyst", "FraudOpsManager", "RecoverySpecialist")
    t = db.auth_transactions.get(tid)
    if not t:
        raise errors.err_not_found("AuthTransaction not found")
    domain.apply_shadow(t)
    return response.success(domain.ser_txn(t))
