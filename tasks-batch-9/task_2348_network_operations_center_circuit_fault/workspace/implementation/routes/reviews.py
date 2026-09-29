"""Vendor performance reviews and the replacement cascade (PRD 3.8)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import REPLACE_SCORE_MAX
from db import base_record, rows, touch
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send
from valid import body, opt_string, req_enum, req_ts

bp = Blueprint("reviews", __name__)

MANAGER_ROLES = ("VendorManager", "PlatformAdmin")
DECISIONS = ("RETAIN", "REMEDIATION_PLAN", "REPLACE")
SWEPT_ORDER_STATES = ("DRAFT", "SUBMITTED", "APPROVED")
SUPERSEDED_REASON = "SUPERSEDED_BY_REPLACEMENT"


@bp.post("/vendor-reviews")
def create_review():
    authenticate(MANAGER_ROLES)
    payload = body()
    carrier = body_ref(payload, "carrier_id", lookup.carrier)
    if carrier is None:
        fail("ERR_INVALID_REQUEST", "carrier_id is required.")
    period_start = req_ts(payload, "period_start")
    period_end = req_ts(payload, "period_end")

    if not period_end > period_start:
        fail("ERR_TIMESTAMP_RANGE_INVALID")

    figures = derive.vendor_scorecard(carrier, period_start, period_end)

    review = base_record()
    review.update(
        {
            "carrier_id": carrier["id"],
            "period_start": period_start,
            "period_end": period_end,
            "chronic_circuit_count": figures["chronic_circuit_count"],
            "credit_ratio": figures["credit_ratio"],
            "mttr_minutes": figures["mttr_minutes"],
            "net_performance_score": figures["net_performance_score"],
            "decision": "PENDING",
            "decided_by_user_id": None,
            "justification": None,
        }
    )
    db.db.reviews[review["id"]] = review
    return send(review, 201)


@bp.post("/vendor-reviews/<id>/decide")
def decide_review(id):
    authenticate(MANAGER_ROLES)
    review = lookup.review(id)
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    justification = opt_string(payload, "justification")

    if review["decision"] != "PENDING":
        fail("ERR_REVIEW_ALREADY_DECIDED")

    score = review["net_performance_score"]
    chronic_count = review["chronic_circuit_count"]

    if decision == "RETAIN" and score < REPLACE_SCORE_MAX:
        fail("ERR_RETAIN_NOT_JUSTIFIED")
    if decision == "REPLACE" and not (score < REPLACE_SCORE_MAX and chronic_count >= 1):
        fail("ERR_REPLACEMENT_NOT_JUSTIFIED")

    review["decision"] = decision
    review["decided_by_user_id"] = g.user_id
    review["justification"] = justification
    touch(review)

    carrier = db.db.carriers.get(review["carrier_id"])

    if decision == "RETAIN" or carrier is None:
        return send(review)

    carrier["watchlist_state"] = "WATCHLIST"

    if decision == "REPLACE":
        replaced_circuit_ids = []
        for circuit in rows(db.db.circuits):
            if circuit["carrier_id"] != carrier["id"]:
                continue
            if circuit["chronic_state"] != "CHRONIC":
                continue
            circuit["chronic_state"] = "REPLACEMENT_APPROVED"
            touch(circuit)
            replaced_circuit_ids.append(circuit["id"])

        for order in rows(db.db.orders):
            if order["circuit_id"] not in replaced_circuit_ids:
                continue
            if order["state"] not in SWEPT_ORDER_STATES:
                continue
            order["state"] = "CANCELLED"
            order["cancel_reason"] = SUPERSEDED_REASON
            touch(order)

        derive.recompute_committed_upgrade(carrier)
        derive.recompute_chronic_circuit_count(carrier)

    touch(carrier)
    return send(review)
