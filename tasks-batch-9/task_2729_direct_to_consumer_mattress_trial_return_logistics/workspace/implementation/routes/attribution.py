"""Retail-partner attribution and price-match claims."""
from flask import Blueprint

from db import base_record, db, now, ordered, paginate, touch
from errors import api_error, invalid
from middleware import require, require_partner_owner
from response import collection, single
from serialize import ATTRIBUTION_CLAIM, dump, dump_many
from services import calc, entities
from util import whole_days
from validate import Fields, Query

bp = Blueprint("attribution", __name__)

CLAIM_TYPES = ("SALES_ATTRIBUTION", "PRICE_MATCH")
CLAIM_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
                  "APPROVED", "REJECTED")
REVIEW_ACTIONS = ("ACCEPT_FOR_REVIEW", "REQUEST_REVISION")
DECISIONS = ("APPROVE", "REJECT")


def _check_eligibility(claim, partner, order):
    """The three eligibility rules, in declared precedence order."""
    elapsed = whole_days(order["delivered_at"], claim["submitted_at"])
    if elapsed is None or elapsed > partner["attribution_window_days"]:
        raise api_error("ERR_ATTRIBUTION_WINDOW_CLOSED",
                        "The partner's attribution window has closed for this "
                        "order")
    if claim["evidence_url_count"] < calc.MIN_CLAIM_EVIDENCE:
        raise api_error("ERR_INSUFFICIENT_EVIDENCE",
                        "At least %d evidence links are required"
                        % calc.MIN_CLAIM_EVIDENCE)
    if claim["claim_type"] == "SALES_ATTRIBUTION":
        if (order["channel"] != "RETAIL_PARTNER"
                or order["retail_partner_id"] != partner["id"]):
            raise api_error("ERR_ATTRIBUTION_CHANNEL_MISMATCH",
                            "This order was not sold through the claiming "
                            "partner")
    else:
        if partner["price_match_policy"] == "NO_MATCH":
            raise api_error("ERR_PRICE_MATCH_NOT_OFFERED",
                            "This partner does not offer price matching")


@bp.route("/attribution-claims", methods=["POST"])
@require("RetailPartner", "PlatformAdmin")
def create_attribution_claim():
    fields = Fields("partner_id", "order_id", "claim_type",
                    "evidence_url_count", "competitor_price_cents")
    partner_id = fields.reference("partner_id")
    order_id = fields.reference("order_id")
    claim_type = fields.enum("claim_type", CLAIM_TYPES)
    evidence_url_count = fields.integer("evidence_url_count", minimum=0)
    competitor_price_cents = fields.integer("competitor_price_cents",
                                            required=False, default=None,
                                            minimum=1)
    if claim_type == "PRICE_MATCH":
        if competitor_price_cents is None:
            raise invalid("competitor_price_cents is required for PRICE_MATCH "
                          "claims")
    else:
        competitor_price_cents = None

    partner = entities.get_retail_partner(partner_id)
    order = entities.get_order(order_id)
    require_partner_owner(partner["id"], "attribution claim")
    if partner["status"] == "SUSPENDED":
        raise api_error("ERR_UNAUTHORIZED",
                        "A SUSPENDED retail partner may not submit claims")

    claim = base_record()
    claim.update({
        "partner_id": partner["id"],
        "order_id": order["id"],
        "claim_type": claim_type,
        "competitor_price_cents": competitor_price_cents,
        "evidence_url_count": evidence_url_count,
        "submitted_at": now(),
        "revision_round_count": 0,
        "commission_cents": 0,
        "price_match_credit_cents": 0,
        "status": "SUBMITTED",
        "resolved_at": None,
    })
    _check_eligibility(claim, partner, order)
    db.attribution_claims[claim["id"]] = claim
    return single(dump(claim, ATTRIBUTION_CLAIM), 201)


@bp.route("/attribution-claims/<claim_id>", methods=["GET"])
@require("RetailPartner", "FinanceController", "PlatformAdmin")
def read_attribution_claim(claim_id):
    claim = entities.get_attribution_claim(claim_id)
    require_partner_owner(claim["partner_id"], "attribution claim")
    return single(dump(claim, ATTRIBUTION_CLAIM), 200)


@bp.route("/attribution-claims", methods=["GET"])
@require("RetailPartner", "FinanceController", "PlatformAdmin")
def list_attribution_claims():
    query = Query("partner_id", "order_id", "claim_type", "status")
    limit, offset = query.page()
    partner_id = query.string("partner_id")
    order_id = query.string("order_id")
    claim_type = query.enum("claim_type", CLAIM_TYPES)
    status = query.enum("status", CLAIM_STATUSES)
    matches = ordered([
        c for c in db.attribution_claims.values()
        if (partner_id is None or c["partner_id"] == partner_id)
        and (order_id is None or c["order_id"] == order_id)
        and (claim_type is None or c["claim_type"] == claim_type)
        and (status is None or c["status"] == status)
    ])
    page, total = paginate(matches, limit, offset)
    return collection(dump_many(page, ATTRIBUTION_CLAIM), limit, offset, total)


@bp.route("/attribution-claims/<claim_id>/review", methods=["POST"])
@require("FinanceController")
def review_attribution_claim(claim_id):
    fields = Fields("action")
    action = fields.enum("action", REVIEW_ACTIONS)
    claim = entities.get_attribution_claim(claim_id)
    if action == "ACCEPT_FOR_REVIEW":
        if claim["status"] != "SUBMITTED":
            raise api_error("ERR_INVALID_ATTRIBUTION_STATE",
                            "Only a SUBMITTED claim can be accepted for "
                            "review")
        claim["status"] = "UNDER_REVIEW"
    else:
        if claim["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_ATTRIBUTION_STATE",
                            "Only a claim UNDER_REVIEW can be sent back for "
                            "revision")
        if claim["revision_round_count"] >= calc.MAX_REVISION_ROUNDS:
            raise api_error("ERR_ROUND_LIMIT_REACHED",
                            "At most %d revision rounds are allowed"
                            % calc.MAX_REVISION_ROUNDS)
        claim["status"] = "REVISION_REQUESTED"
    touch(claim)
    return single(dump(claim, ATTRIBUTION_CLAIM), 200)


@bp.route("/attribution-claims/<claim_id>/resubmit", methods=["POST"])
@require("RetailPartner")
def resubmit_attribution_claim(claim_id):
    fields = Fields("evidence_url_count", "competitor_price_cents")
    evidence_url_count = fields.integer("evidence_url_count", minimum=0)
    competitor_price_cents = fields.integer("competitor_price_cents",
                                            required=False, default=None,
                                            minimum=1)
    claim = entities.get_attribution_claim(claim_id)
    require_partner_owner(claim["partner_id"], "attribution claim")
    if claim["status"] != "REVISION_REQUESTED":
        raise api_error("ERR_INVALID_ATTRIBUTION_STATE",
                        "Only a claim in REVISION_REQUESTED can be resubmitted")
    if evidence_url_count < calc.MIN_CLAIM_EVIDENCE:
        raise api_error("ERR_INSUFFICIENT_EVIDENCE",
                        "At least %d evidence links are required"
                        % calc.MIN_CLAIM_EVIDENCE)
    if claim["revision_round_count"] >= calc.MAX_REVISION_ROUNDS:
        raise api_error("ERR_ROUND_LIMIT_REACHED",
                        "At most %d revision rounds are allowed"
                        % calc.MAX_REVISION_ROUNDS)
    claim["evidence_url_count"] = evidence_url_count
    if claim["claim_type"] == "PRICE_MATCH" and competitor_price_cents:
        claim["competitor_price_cents"] = competitor_price_cents
    claim["revision_round_count"] = claim["revision_round_count"] + 1
    claim["submitted_at"] = now()
    claim["status"] = "SUBMITTED"
    touch(claim)
    return single(dump(claim, ATTRIBUTION_CLAIM), 200)


@bp.route("/attribution-claims/<claim_id>/resolve", methods=["POST"])
@require("FinanceController")
def resolve_attribution_claim(claim_id):
    fields = Fields("decision")
    decision = fields.enum("decision", DECISIONS)
    claim = entities.get_attribution_claim(claim_id)
    if claim["status"] != "UNDER_REVIEW":
        raise api_error("ERR_INVALID_ATTRIBUTION_STATE",
                        "Only a claim UNDER_REVIEW can be resolved")
    partner = entities.get_retail_partner(claim["partner_id"])
    order = entities.get_order(claim["order_id"])

    if decision == "REJECT":
        claim["commission_cents"] = 0
        claim["price_match_credit_cents"] = 0
        claim["status"] = "REJECTED"
        claim["resolved_at"] = now()
        touch(claim)
        return single(dump(claim, ATTRIBUTION_CLAIM), 200)

    _check_eligibility(claim, partner, order)
    if claim["claim_type"] == "SALES_ATTRIBUTION":
        claim["commission_cents"] = calc.commission_amount(
            order["paid_amount_cents"], partner["commission_bps"])
        claim["price_match_credit_cents"] = 0
    else:
        credit = calc.price_match_credit(partner["price_match_policy"],
                                         order["gross_price_cents"],
                                         claim["competitor_price_cents"])
        claim["price_match_credit_cents"] = credit
        claim["commission_cents"] = 0
        order["price_match_credit_cents"] = (
            order["price_match_credit_cents"] + credit)
        touch(order)
    claim["status"] = "APPROVED"
    claim["resolved_at"] = now()
    touch(claim)
    return single(dump(claim, ATTRIBUTION_CLAIM), 200)
