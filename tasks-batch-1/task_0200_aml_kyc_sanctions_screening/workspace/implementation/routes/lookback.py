"""Lookback reviews and items (PRD §3.10)."""

from flask import Blueprint, request

import db
import services
import clock
from routes.accounts import mint_alert
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_INVALID_DECISION,
    ERR_REVIEW_EMPTY,
    ERR_ITEM_NOT_QUEUED,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_string,
    require_field,
    parse_pagination,
    sort_and_paginate,
)

bp = Blueprint("lookback", __name__)

READ_ROLES = {"ComplianceOfficer", "Analyst", "QualityReviewer", "PlatformAdmin"}


def _parse_window_ts(body, name):
    raw = require_field(body, name)
    if not isinstance(raw, str):
        raise err(ERR_INVALID_REQUEST, f"{name} must be an ISO 8601 string.")
    try:
        return clock.parse_iso8601(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"{name} must be a valid ISO 8601 timestamp.")


# ---------------------------------------------------------------------------
# POST /lookback-reviews  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/lookback-reviews", methods=["POST"])
def plan_review():
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()

    reason = require_string(body, "reason")
    start_dt = _parse_window_ts(body, "window_start")
    end_dt = _parse_window_ts(body, "window_end")

    # priority 16: window_end strictly after window_start (PRD §3.10)
    if not (end_dt > start_dt):
        raise err(ERR_INVALID_WINDOW, "window_end must be strictly after window_start.")

    base = db.common_create_fields()
    review = {
        **base,
        "reason": reason,
        "window_start": clock.format_iso8601(start_dt),
        "window_end": clock.format_iso8601(end_dt),
        "status": "PLANNED",
        "total_items": 0,
        "cleared_items": 0,
        "escalated_items": 0,
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
    }
    db.lookback_reviews[review["id"]] = review
    services.audit("LookbackReview", review["id"], "REVIEW_PLANNED", user_id, role)
    return object_response(db.public(review), 201)


@bp.route("/lookback-reviews/<rid>", methods=["GET"])
def get_review(rid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    review = require_found(db.lookback_reviews.get(rid))
    return object_response(db.public(review))


# ---------------------------------------------------------------------------
# POST /lookback-reviews/{id}/enqueue  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/lookback-reviews/<rid>/enqueue", methods=["POST"])
def enqueue_review(rid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    review = require_found(db.lookback_reviews.get(rid))

    if review["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "enqueue requires review in PLANNED.")

    start_dt = review["_window_start_dt"]
    end_dt = review["_window_end_dt"]

    # half-open [start, end): account in-scope iff >=1 own in-window transaction.
    scoped_accounts = []
    seen = set()
    # iterate transactions in stable order so item creation order is deterministic
    for t in sorted(db.transactions.values(), key=lambda x: (x["created_at"], x.get("_seq", 0))):
        posted = clock.parse_iso8601(t["posted_at"])
        if start_dt <= posted < end_dt:
            acc_id = t["account_id"]
            if acc_id not in seen:
                seen.add(acc_id)
                scoped_accounts.append(acc_id)

    # priority 25: at least one in-window account (PRD §3.10)
    if not scoped_accounts:
        raise err(ERR_REVIEW_EMPTY, "No in-window account; review stays PLANNED.")

    for acc_id in scoped_accounts:
        base = db.common_create_fields()
        item = {
            **base,
            "lookback_review_id": rid,
            "account_id": acc_id,
            "item_status": "QUEUED",
            "generated_alert_id": None,
        }
        db.lookback_review_items[item["id"]] = item

    review["total_items"] = len(scoped_accounts)
    review["status"] = "IN_PROGRESS"
    db.touch(review)
    services.audit("LookbackReview", rid, "REVIEW_ENQUEUED", user_id, role)
    return object_response(db.public(review))


# ---------------------------------------------------------------------------
# POST /lookback-reviews/{id}/cancel  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/lookback-reviews/<rid>/cancel", methods=["POST"])
def cancel_review(rid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    review = require_found(db.lookback_reviews.get(rid))

    if review["status"] != "PLANNED":
        raise err(ERR_INVALID_STATE, "cancel requires review in PLANNED.")
    review["status"] = "CANCELLED"
    db.touch(review)
    services.audit("LookbackReview", rid, "REVIEW_CANCELLED", user_id, role)
    return object_response(db.public(review))


@bp.route("/lookback-reviews/<rid>/items", methods=["GET"])
def list_review_items(rid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.lookback_reviews.get(rid))
    limit, offset = parse_pagination(request.args)
    rows = [i for i in db.lookback_review_items.values() if i["lookback_review_id"] == rid]
    status = request.args.get("item_status")
    if status is not None:
        rows = [i for i in rows if i["item_status"] == status]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(i) for i in page], limit, offset, total)


@bp.route("/lookback-items/<iid>", methods=["GET"])
def get_item(iid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    item = require_found(db.lookback_review_items.get(iid))
    return object_response(db.public(item))


@bp.route("/lookback-items", methods=["GET"])
def list_items():
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.lookback_review_items.values())
    acc = request.args.get("account_id")
    if acc is not None:
        rows = [i for i in rows if i["account_id"] == acc]
    gen = request.args.get("generated_alert_id")
    if gen is not None:
        rows = [i for i in rows if i["generated_alert_id"] == gen]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /lookback-items/{id}/disposition  (Analyst)
# ---------------------------------------------------------------------------
@bp.route("/lookback-items/<iid>/disposition", methods=["POST"])
def disposition_item(iid):
    user_id, role = authenticate()
    require_role(role, {"Analyst"})
    item = require_found(db.lookback_review_items.get(iid))
    body = get_body()

    # priority 21: decision must be CLEAR or ESCALATE
    decision = require_field(body, "decision")
    if decision not in {"CLEAR", "ESCALATE"}:
        raise err(ERR_INVALID_DECISION, "decision must be CLEAR or ESCALATE.")

    review = db.lookback_reviews.get(item["lookback_review_id"])

    # priority 22: item must be QUEUED AND parent review IN_PROGRESS (PRD §3.10)
    if item["item_status"] != "QUEUED" or review is None or review["status"] != "IN_PROGRESS":
        raise err(ERR_ITEM_NOT_QUEUED, "Item must be QUEUED and parent review IN_PROGRESS.")

    if decision == "CLEAR":
        item["item_status"] = "CLEARED"
        db.touch(item)
        review["cleared_items"] += 1
        db.touch(review)
        services.audit("LookbackReviewItem", iid, "ITEM_CLEARED", user_id, role)
    else:  # ESCALATE
        item["item_status"] = "ESCALATED"
        # mint Alert(HIGH_RISK_GEO, OPEN) for item.account_id; cascade account (PRD §3.10)
        account = db.accounts.get(item["account_id"])
        if account is not None:
            alert = mint_alert(account, "HIGH_RISK_GEO", user_id, role)
            item["generated_alert_id"] = alert["id"]
        db.touch(item)
        review["escalated_items"] += 1
        db.touch(review)
        services.audit("LookbackReviewItem", iid, "ITEM_ESCALATED", user_id, role)

    # compound bubble-up: all items terminal -> COMPLETED (PRD §3.10)
    if (
        review["total_items"] > 0
        and review["cleared_items"] + review["escalated_items"] == review["total_items"]
    ):
        review["status"] = "COMPLETED"
        db.touch(review)
        services.audit("LookbackReview", review["id"], "REVIEW_COMPLETED", user_id, role)

    return object_response(db.public(item))
