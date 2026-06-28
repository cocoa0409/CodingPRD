"""Submission endpoints incl. DMV decision cascade (PRD §3.4; scaffold §1.5)."""

from flask import Blueprint, g, request

import errors
import repo
from db import db
from domain import lien_packets_for_transaction
from helpers import get_json_body, require_enum, parse_pagination, paginate
from middleware import require_roles
from response import success, list_success
from serializers import submission_out

bp = Blueprint("submissions", __name__)

MAX_REJECTION_ROUNDS = 3


@bp.route("/dmv/submissions", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher", "IntakeClerk")
def list_submissions():
    limit, offset = parse_pagination()
    transaction_id = request.args.get("transaction_id")
    submission_status = request.args.get("submission_status")
    priority_class = request.args.get("priority_class")
    leg_id = request.args.get("leg_id")
    items = list(db.submissions.values())
    if transaction_id is not None:
        items = [s for s in items if s["transaction_id"] == transaction_id]
    if submission_status is not None:
        items = [s for s in items if s["submission_status"] == submission_status]
    if priority_class is not None:
        items = [s for s in items if s["priority_class"] == priority_class]
    if leg_id is not None:
        items = [s for s in items if s["leg_id"] == leg_id]
    page, total = paginate(items, limit, offset)
    return list_success([submission_out(s) for s in page], limit, offset, total)


@bp.route("/dmv/submissions/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "RunnerDispatcher", "IntakeClerk", "FeeAnalyst")
def get_submission(sid):
    s = db.submissions.get(sid)
    if s is None:
        raise errors.not_found("submission not found")
    return success(submission_out(s), 200)


@bp.route("/dmv/submissions/<sid>/decision", methods=["POST"])
@require_roles("RunnerDispatcher")
def submission_decision(sid):
    body = get_json_body()
    s = db.submissions.get(sid)
    if s is None:
        raise errors.not_found("submission not found")

    outcome = require_enum(body, "outcome", {"ACCEPTED", "DMV_REJECTED"})

    # State eligibility (priority 5): submission must be ASSIGNED.
    if s["submission_status"] != "ASSIGNED":
        raise errors.invalid_state("submission must be ASSIGNED for a decision")

    # The leg's trip must be RETURNED (priority 14).
    leg = db.runner_legs.get(s["leg_id"]) if s["leg_id"] else None
    if leg is None:
        raise errors.invalid_state("submission has no attached leg")
    trip = db.runner_trips.get(leg["trip_id"])
    if trip is None or trip["trip_status"] != "RETURNED":
        raise errors.trip_not_returned("the leg's trip has not RETURNED")

    txn = db.transactions.get(s["transaction_id"])

    if outcome == "ACCEPTED":
        s["submission_status"] = "ACCEPTED"
        repo.bump(s)
        leg["leg_status"] = "RESOLVED"
        repo.bump(leg)
        # Reflect onto the transaction: SUBMITTED -> APPROVED.
        if txn is not None and txn["lifecycle_status"] == "SUBMITTED":
            txn["lifecycle_status"] = "APPROVED"
            # A DRAFT lien packet, if any, is left in DRAFT (no change).
            repo.bump(txn)
        return success(submission_out(s), 200)

    # DMV_REJECTED requires a rejection_reason.
    rejection_reason = body.get("rejection_reason")
    if not isinstance(rejection_reason, str) or rejection_reason == "":
        raise errors.invalid_request("rejection_reason is required on DMV_REJECTED")

    s["submission_status"] = "DMV_REJECTED"
    s["rejection_reason"] = rejection_reason
    repo.bump(s)
    leg["leg_status"] = "RESOLVED"
    repo.bump(leg)

    # Rejection cascade onto the transaction.
    if txn is not None and txn["lifecycle_status"] == "SUBMITTED":
        txn["rejection_round"] = txn["rejection_round"] + 1
        txn["document_status"] = "INCOMPLETE"
        # Auto-cancel when rejection_round reaches the cap at this decision.
        if txn["rejection_round"] >= MAX_REJECTION_ROUNDS:
            txn["lifecycle_status"] = "CANCELLED"
            for p in lien_packets_for_transaction(txn["id"]):
                if p["packet_status"] == "DRAFT":
                    p["packet_status"] = "VOIDED"
                    repo.bump(p)
        else:
            txn["lifecycle_status"] = "REJECTED"
        repo.bump(txn)

    return success(submission_out(s), 200)
