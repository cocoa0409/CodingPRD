"""Application routes (PRD §3.2). Underwriting + revision loop.

Validation priority order (PRD §2.9) is enforced per-endpoint:
auth -> role -> SoD -> not-found -> invalid-request -> invalid-state ->
stale-version -> blocklist -> feed-stale -> excess-nsf -> score-floor -> ...
"""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import db
import serialize
from common import (parse_body, require_fields, require_int, stamp_create, touch,
                    list_response, now)
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_MERCHANT_BLOCKLISTED, ERR_FEED_STALE, ERR_EXCESS_NSF,
                    ERR_SCORE_BELOW_FLOOR)
from lookups import get_application, get_merchant, get_bank_feed
from middleware import auth_and_role
from response import object_response
from services import calc

bp = Blueprint("applications", __name__)

DECLINE_REASONS = {"LOW_SCORE", "STALE_FEED", "EXCESS_NSF", "BLOCKLISTED"}


def _compute_score(application, feed):
    merchant = db.merchants[application["merchant_id"]]
    return calc.underwriting_risk_score(
        avg_daily_balance_cents=feed["avg_daily_balance_cents"],
        nsf_count_90d=feed["nsf_count_90d"],
        deposit_volume_cents=feed["deposit_volume_cents"],
        monthly_revenue_cents=merchant["monthly_revenue_cents"],
        requested_limit_cents=application["requested_limit_cents"],
    )


@bp.post("/applications")
def create_application():
    auth_and_role(["Underwriter"])
    body = parse_body()
    require_fields(body, ["merchant_id", "bank_feed_id", "requested_limit_cents"])
    # FK existence (priority 4) before well-formedness of scalar fields.
    merchant = get_merchant(body["merchant_id"])
    feed = get_bank_feed(body["bank_feed_id"])
    requested = require_int(body, "requested_limit_cents", exclusive_min=0)

    record = {
        "merchant_id": merchant["id"],
        "bank_feed_id": feed["id"],
        "requested_limit_cents": requested,
        "submitted_by_user_id": None,
        "status": "DRAFT",
        "risk_score": None,
        "approved_limit_cents": None,
        "pricing_tier": None,
        "decline_reason": None,
    }
    stamp_create(record)
    db.applications[record["id"]] = record
    return object_response(serialize.application(record), 201)


@bp.get("/applications/<rid>")
def fetch_application(rid):
    auth_and_role(["Underwriter", "CreditOfficer"])
    a = get_application(rid)
    return object_response(serialize.application(a), 200)


@bp.get("/applications")
def list_applications():
    auth_and_role(["Underwriter", "CreditOfficer"])
    merchant_id = request.args.get("merchant_id")
    bank_feed_id = request.args.get("bank_feed_id")
    status = request.args.get("status")
    apps = list(db.applications.values())
    if merchant_id is not None:
        apps = [a for a in apps if a["merchant_id"] == merchant_id]
    if bank_feed_id is not None:
        apps = [a for a in apps if a["bank_feed_id"] == bank_feed_id]
    if status is not None:
        apps = [a for a in apps if a["status"] == status]
    return list_response(apps, serialize.application)


@bp.post("/applications/<rid>/submit")
def submit_application(rid):
    user_id, _ = auth_and_role(["Underwriter"])
    a = get_application(rid)
    body = parse_body()

    # optional bank_feed_id override: FK existence (priority 4).
    feed_id = body.get("bank_feed_id")
    if feed_id is not None:
        feed = get_bank_feed(feed_id)
    else:
        feed = get_bank_feed(a["bank_feed_id"])

    # state legality (priority 6): submit allowed from DRAFT or NEEDS_REVISION.
    if a["status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise err(ERR_INVALID_STATE, "Application not in a submittable state")

    # feed freshness (priority 9).
    if feed["status"] != "FRESH":
        raise err(ERR_FEED_STALE, "Referenced bank feed is stale")

    if feed_id is not None:
        a["bank_feed_id"] = feed["id"]
    a["submitted_by_user_id"] = user_id
    a["status"] = "SUBMITTED"
    a["risk_score"] = _compute_score(a, feed)
    touch(a)
    return object_response(serialize.application(a), 200)


@bp.post("/applications/<rid>/approve")
def approve_application(rid):
    user_id, _ = auth_and_role(["Underwriter"])
    a = get_application(rid)

    # SoD (priority 3) — approver must differ from submitter.
    if a.get("submitted_by_user_id") is not None and user_id == a["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from submitter")

    # state legality (priority 6).
    if a["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application is not SUBMITTED")

    merchant = db.merchants[a["merchant_id"]]
    feed = db.bank_feeds[a["bank_feed_id"]]

    # blocklist (priority 8).
    if merchant["status"] == "BLOCKLISTED":
        raise err(ERR_MERCHANT_BLOCKLISTED, "Merchant is blocklisted")
    # feed freshness (priority 9).
    if feed["status"] != "FRESH":
        raise err(ERR_FEED_STALE, "Referenced bank feed is stale")
    # excess NSF (priority 10).
    if feed["nsf_count_90d"] > C.NSF_UNDERWRITE_MAX:
        raise err(ERR_EXCESS_NSF, "Feed NSF count exceeds underwriting maximum")
    # score floor (priority 11).
    score = a["risk_score"]
    if score is None or score < C.APPROVAL_SCORE_FLOOR:
        raise err(ERR_SCORE_BELOW_FLOOR, "Risk score below approval floor")

    tier = calc.tier_for_score(score)
    a["approved_limit_cents"] = calc.approved_limit(
        requested_limit_cents=a["requested_limit_cents"],
        avg_daily_balance_cents=feed["avg_daily_balance_cents"],
        tier=tier,
    )
    a["pricing_tier"] = tier
    a["status"] = "APPROVED"
    touch(a)
    return object_response(serialize.application(a), 200)


@bp.post("/applications/<rid>/request-revision")
def request_revision(rid):
    user_id, _ = auth_and_role(["Underwriter"])
    a = get_application(rid)
    if a.get("submitted_by_user_id") is not None and user_id == a["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from submitter")
    if a["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application is not SUBMITTED")
    a["risk_score"] = None
    a["status"] = "NEEDS_REVISION"
    touch(a)
    return object_response(serialize.application(a), 200)


@bp.post("/applications/<rid>/decline")
def decline_application(rid):
    user_id, _ = auth_and_role(["Underwriter"])
    a = get_application(rid)
    if a.get("submitted_by_user_id") is not None and user_id == a["submitted_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from submitter")
    body = parse_body()
    require_fields(body, ["decline_reason"])
    reason = body["decline_reason"]
    if reason not in DECLINE_REASONS:
        raise err(ERR_INVALID_REQUEST, "Invalid decline_reason")
    if a["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application is not SUBMITTED")
    a["decline_reason"] = reason
    a["status"] = "DECLINED"
    touch(a)
    return object_response(serialize.application(a), 200)
