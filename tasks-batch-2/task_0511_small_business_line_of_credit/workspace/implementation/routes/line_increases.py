"""LineIncreaseRequest routes (PRD §3.7). Request, approve (OCC + non-regression
+ cross-entity limit write), deny."""
from flask import Blueprint, request

import constants as C
import db
import serialize
from common import parse_body, require_fields, require_int, stamp_create, touch, list_response
from errors import (err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
                    ERR_FEED_STALE, ERR_SCORE_BELOW_FLOOR)
from lookups import get_credit_line, get_bank_feed, get_line_increase_request
from middleware import auth_and_role
from response import object_response
from services import calc, ledger

bp = Blueprint("line_increases", __name__)

DENIAL_REASONS = {"STALE_FEED", "SCORE_REGRESSION", "LINE_NOT_ACTIVE"}


@bp.post("/credit-lines/<rid>/line-increase-requests")
def request_increase(rid):
    auth_and_role(["Servicer"])
    cl = get_credit_line(rid)
    body = parse_body()
    require_fields(body, ["latest_bank_feed_id", "requested_limit_cents"])
    feed = get_bank_feed(body["latest_bank_feed_id"])
    requested = require_int(body, "requested_limit_cents", exclusive_min=0)

    record = {
        "credit_line_id": cl["id"],
        "latest_bank_feed_id": feed["id"],
        "requested_limit_cents": requested,
        "approved_limit_cents": None,
        "status": "PENDING",
        "denial_reason": None,
    }
    stamp_create(record)
    db.line_increase_requests[record["id"]] = record
    return object_response(serialize.line_increase_request(record), 201)


@bp.get("/line-increase-requests/<rid>")
def fetch_increase(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    lir = get_line_increase_request(rid)
    return object_response(serialize.line_increase_request(lir), 200)


@bp.get("/credit-lines/<rid>/line-increase-requests")
def list_increases_for_line(rid):
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    get_credit_line(rid)
    status = request.args.get("status")
    items = [x for x in db.line_increase_requests.values() if x["credit_line_id"] == rid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, serialize.line_increase_request)


@bp.get("/line-increase-requests")
def list_increases():
    auth_and_role(["Underwriter", "Servicer", "CreditOfficer"])
    credit_line_id = request.args.get("credit_line_id")
    latest_bank_feed_id = request.args.get("latest_bank_feed_id")
    status = request.args.get("status")
    items = list(db.line_increase_requests.values())
    if credit_line_id is not None:
        items = [x for x in items if x["credit_line_id"] == credit_line_id]
    if latest_bank_feed_id is not None:
        items = [x for x in items if x["latest_bank_feed_id"] == latest_bank_feed_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    return list_response(items, serialize.line_increase_request)


@bp.post("/line-increase-requests/<rid>/approve")
def approve_increase(rid):
    auth_and_role(["CreditOfficer"])
    lir = get_line_increase_request(rid)
    body = parse_body()
    expected = require_int(body, "expected_credit_line_version", minimum=0)
    cl = db.credit_lines[lir["credit_line_id"]]

    # state legality (priority 6): request PENDING AND parent line ACTIVE (cross-entity guard).
    if lir["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Increase request is not PENDING")
    if cl["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent line is not ACTIVE")

    # OCC (priority 7).
    if expected != cl["version"]:
        raise err(ERR_STALE_VERSION, "expected_credit_line_version does not match")

    feed = db.bank_feeds[lir["latest_bank_feed_id"]]
    # feed freshness (priority 9).
    if feed["status"] != "FRESH":
        raise err(ERR_FEED_STALE, "Latest bank feed is stale")

    # non-regression (priority 11): new_score >= prior_score.
    merchant = db.merchants[cl["merchant_id"]]
    new_score = calc.underwriting_risk_score(
        avg_daily_balance_cents=feed["avg_daily_balance_cents"],
        nsf_count_90d=feed["nsf_count_90d"],
        deposit_volume_cents=feed["deposit_volume_cents"],
        monthly_revenue_cents=merchant["monthly_revenue_cents"],
        requested_limit_cents=lir["requested_limit_cents"],
    )
    originating_app = db.applications[cl["application_id"]]
    prior_score = originating_app["risk_score"]
    if prior_score is None or new_score < prior_score:
        raise err(ERR_SCORE_BELOW_FLOOR, "Increase score regresses below prior score")

    # increase-variant limit: floored at current limit, capped by raw advance cap.
    tier = calc.tier_for_score(new_score)
    if tier is None:
        # score below approval floor: treat as regression-style rejection.
        raise err(ERR_SCORE_BELOW_FLOOR, "Increase score below approval floor")
    approved = calc.approved_limit(
        requested_limit_cents=lir["requested_limit_cents"],
        avg_daily_balance_cents=feed["avg_daily_balance_cents"],
        tier=tier,
        current_limit_cents=cl["credit_limit_cents"],
    )
    lir["approved_limit_cents"] = approved
    lir["status"] = "APPROVED"
    touch(lir)

    # cross-entity: write new limit onto parent line, recompute available, bump version.
    cl["credit_limit_cents"] = approved
    ledger.recompute_outstanding(cl)
    touch(cl)
    return object_response(serialize.line_increase_request(lir), 200)


@bp.post("/line-increase-requests/<rid>/deny")
def deny_increase(rid):
    auth_and_role(["CreditOfficer"])
    lir = get_line_increase_request(rid)
    body = parse_body()
    require_fields(body, ["denial_reason"])
    reason = body["denial_reason"]
    if reason not in DENIAL_REASONS:
        raise err(ERR_INVALID_REQUEST, "Invalid denial_reason")
    if lir["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Increase request is not PENDING")
    lir["denial_reason"] = reason
    lir["status"] = "DENIED"
    touch(lir)
    return object_response(serialize.line_increase_request(lir), 200)
