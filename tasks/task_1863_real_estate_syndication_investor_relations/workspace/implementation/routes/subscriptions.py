"""Subscription lifecycle: draft -> submitted -> verified -> approved -> funded (PRD 3.3)."""
from datetime import timedelta

from flask import Blueprint

import resolve
from db import db
from errors import raise_error
from middleware import SPONSOR, COMPLIANCE, AGENT, INVESTOR, ALL_ROLES, endpoint
from response import success_list, success_object
from serializers import ser_subscription
from services.domain import stamp_new, touch, sorted_items
from util import CLOCK, fmt_dt
from validate import get_body, req_int, req_str, pagination, apply_filters

bp = Blueprint("subscriptions", __name__)
RS = {"strict_slashes": False}

REQUIRED_SUBMIT_DOCS = ("SUBSCRIPTION_AGREEMENT", "W9", "SUITABILITY_QUESTIONNAIRE")
# committed_cents >= 100000_00 ($100k) requires ACCREDITED / QUALIFIED_PURCHASER.
CLASS_GATE_CENTS = 100000_00


def _visible_subscription(caller, sub):
    """Investor role sees only its own subscriptions (RBAC: subscriptions (own))."""
    if caller.role == INVESTOR and sub["investor_id"] != caller.user_id:
        raise_error("ERR_SUBSCRIPTION_NOT_FOUND", f"subscription not found: {sub['id']}")


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def create_subscription(caller, syndicationId, offeringId):
    off = resolve.offering(syndicationId, offeringId)
    body = get_body()
    investor_id = req_str(body, "investor_id")
    committed = req_int(body, "committed_cents", minimum=0)
    if db["investors"].get(investor_id) is None:
        raise_error("ERR_INVESTOR_NOT_FOUND", f"investor not found: {investor_id}")
    if off["status"] != "OPEN":
        raise_error("ERR_OFFERING_NOT_OPEN", "offering is not OPEN for new subscriptions")
    if caller.user_id != investor_id:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only create its own subscription")
    s = {
        "offering_id": offeringId,
        "investor_id": investor_id,
        "committed_cents": committed,
        "funded_cents": 0,
        "unreturned_capital_cents": 0,
        "suitability_verified_by": None,
        "accreditation_verified_by": None,
        "accreditation_verified_at": None,
        "funded_at": None,
        "status": "DRAFT",
        "_pref_ledger": 0,
        "_accrued_frozen": True,
        "_frozen_accrued": 0,
    }
    stamp_new(s)
    db["subscriptions"][s["id"]] = s
    return success_object(ser_subscription(s), 201)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def list_subscriptions(caller, syndicationId, offeringId):
    resolve.offering(syndicationId, offeringId)
    limit, offset = pagination()
    items = [s for s in db["subscriptions"].values() if s["offering_id"] == offeringId]
    if caller.role == INVESTOR:
        items = [s for s in items if s["investor_id"] == caller.user_id]
    items = apply_filters(sorted_items(items),
                          {"status": "status", "investor_id": "investor_id"})
    page = items[offset:offset + limit]
    return success_list([ser_subscription(o) for o in page], len(items), limit, offset)


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>",
          methods=["GET"], **RS)
@endpoint(*ALL_ROLES)
def get_subscription(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    _visible_subscription(caller, sub)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/submit",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def submit_subscription(caller, syndicationId, offeringId, subscriptionId):
    syn = resolve.syndication(syndicationId)
    off = resolve.offering(syndicationId, offeringId)
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE",
                    f"cannot submit a subscription in status {sub['status']}")
    if syn["status"] != "ACTIVE":
        raise_error("ERR_SYNDICATION_NOT_ACTIVE", "syndication must be ACTIVE to submit")
    if off["status"] != "OPEN":
        raise_error("ERR_OFFERING_NOT_OPEN", "offering must be OPEN to submit")
    # 1) required documents, all ACCEPTED.
    accepted = {d["doc_type"] for d in db["documents"].values()
                if d["subscription_id"] == sub["id"] and d["review_status"] == "ACCEPTED"}
    if not set(REQUIRED_SUBMIT_DOCS) <= accepted:
        raise_error("ERR_MISSING_REQUIRED_DOCUMENTS",
                    "SUBSCRIPTION_AGREEMENT, W9 and SUITABILITY_QUESTIONNAIRE must be ACCEPTED")
    # 2) commitment floor.
    if sub["committed_cents"] < off["min_subscription_cents"]:
        raise_error("ERR_BELOW_MIN_SUBSCRIPTION",
                    "committed_cents is below the offering minimum")
    # 3) Rule 506(b) non-accredited cap (other non-terminal subscriptions).
    inv = db["investors"].get(sub["investor_id"])
    if inv is not None and inv["investor_class"] == "NON_ACCREDITED":
        count = 0
        for other in db["subscriptions"].values():
            if (other["offering_id"] == offeringId and other["id"] != sub["id"]
                    and other["status"] not in ("FUNDED", "WITHDRAWN")):
                oinv = db["investors"].get(other["investor_id"])
                if oinv is not None and oinv["investor_class"] == "NON_ACCREDITED":
                    count += 1
        if count >= off["max_non_accredited_count"]:
            raise_error("ERR_NON_ACCREDITED_CAP_REACHED",
                        "offering's non-accredited investor cap is reached")
    sub["status"] = "SUBMITTED"
    touch(sub)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/verify-accreditation",
          methods=["POST"], **RS)
@endpoint(COMPLIANCE)
def verify_accreditation(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] != "SUBMITTED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot verify accreditation in status {sub['status']}")
    # Segregation of duties: the officer may not verify their own subscription.
    if caller.user_id == sub["investor_id"]:
        raise_error("ERR_SELF_VERIFICATION_FORBIDDEN",
                    "compliance officer cannot verify their own subscription")
    has_letter = any(
        d["subscription_id"] == sub["id"] and d["doc_type"] == "ACCREDITATION_LETTER"
        and d["review_status"] == "ACCEPTED"
        for d in db["documents"].values()
    )
    if not has_letter:
        raise_error("ERR_ACCREDITATION_DOC_MISSING",
                    "an ACCEPTED ACCREDITATION_LETTER document is required")
    inv = db["investors"].get(sub["investor_id"])
    if (sub["committed_cents"] >= CLASS_GATE_CENTS and inv is not None
            and inv["investor_class"] not in ("ACCREDITED", "QUALIFIED_PURCHASER")):
        raise_error("ERR_INVESTOR_CLASS_INSUFFICIENT",
                    "commitments of $100,000 or more require ACCREDITED or QUALIFIED_PURCHASER")
    now = CLOCK.now()
    sub["accreditation_verified_by"] = caller.user_id
    sub["accreditation_verified_at"] = fmt_dt(now)
    sub["status"] = "ACCREDITATION_VERIFIED"
    touch(sub)
    if inv is not None:
        inv["accreditation_expires_on"] = fmt_dt(now + timedelta(days=90))
        touch(inv)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/approve-suitability",
          methods=["POST"], **RS)
@endpoint(COMPLIANCE)
def approve_suitability(caller, syndicationId, offeringId, subscriptionId):
    off = resolve.offering(syndicationId, offeringId)
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] != "ACCREDITATION_VERIFIED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot approve suitability in status {sub['status']}")
    # Segregation of duties: approver must differ from the accreditation verifier.
    if caller.user_id == sub["accreditation_verified_by"]:
        raise_error("ERR_SELF_APPROVAL_FORBIDDEN",
                    "suitability approver must differ from the accreditation verifier")
    sub["suitability_verified_by"] = caller.user_id
    # Chained transition: ACCREDITATION_VERIFIED -> SUITABILITY_APPROVED -> AWAITING_FUNDING.
    sub["status"] = "AWAITING_FUNDING"
    touch(sub)
    # Offering.total_committed_cents grows by committed_cents (computed field);
    # the scaffold pins an explicit Offering version bump here.
    touch(off)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/reject-suitability",
          methods=["POST"], **RS)
@endpoint(COMPLIANCE)
def reject_suitability(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] != "ACCREDITATION_VERIFIED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot reject suitability in status {sub['status']}")
    sub["status"] = "SUITABILITY_REJECTED"
    sub["accreditation_verified_by"] = None
    touch(sub)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/resubmit",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def resubmit_subscription(caller, syndicationId, offeringId, subscriptionId):
    off = resolve.offering(syndicationId, offeringId)
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] != "SUITABILITY_REJECTED":
        raise_error("ERR_INVALID_STATE",
                    f"cannot resubmit a subscription in status {sub['status']}")
    if off["status"] != "OPEN":
        raise_error("ERR_OFFERING_NOT_OPEN", "offering must be OPEN to resubmit")
    sub["status"] = "SUBMITTED"
    touch(sub)
    return success_object(ser_subscription(sub))


@bp.route("/syndications/<syndicationId>/offerings/<offeringId>/subscriptions/<subscriptionId>/withdraw",
          methods=["POST"], **RS)
@endpoint(INVESTOR)
def withdraw_subscription(caller, syndicationId, offeringId, subscriptionId):
    sub = resolve.subscription(syndicationId, offeringId, subscriptionId)
    if sub["status"] not in ("DRAFT", "SUBMITTED"):
        raise_error("ERR_INVALID_STATE",
                    f"cannot withdraw a subscription in status {sub['status']}")
    if caller.user_id != sub["investor_id"]:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS",
                    "an investor may only withdraw its own subscription")
    sub["status"] = "WITHDRAWN"
    touch(sub)
    return success_object(ser_subscription(sub))
