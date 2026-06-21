"""ProofOfLoss endpoints: file, get, accept, reject (PRD §3.9).

A sworn proof-of-loss supports a claim. Accept enforces the inclusive 60-day
deadline and the sworn-figure reconciliation. Reject bounces the supported
UNDER_REVIEW claim back to SUBMITTED.
"""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts
from clock import clock, format_iso8601_ms, parse_iso8601, floor_days_between
from middleware import require_roles
from response import success
from serializers import serialize_proof_of_loss
from helpers import get_body, require_str, opt_number
from services.calculations import PROOF_OF_LOSS_DEADLINE_DAYS

bp = Blueprint("proofs_of_loss", __name__)


@bp.route("/proofs-of-loss", methods=["POST"])
@require_roles("PolicyHolder")
def file_proof():
    body = get_body()
    claim_id = require_str(body, "claim_id")
    documented_building_loss = opt_number(body, "documented_building_loss", 0)
    documented_contents_loss = opt_number(body, "documented_contents_loss", 0)

    # Existence (priority 3): claim_id FK must resolve.
    claim = db.claims.get(claim_id)
    if claim is None:
        raise errors.not_found("Claim not found")

    # Ownership (priority 4): a PolicyHolder may only file for their own claim.
    if claim["claimant_id"] != g.user_id:
        raise errors.not_resource_owner("Not the claimant of this claim")

    now = clock.now()
    date_of_loss = parse_iso8601(claim["date_of_loss"])
    days_after_loss = floor_days_between(date_of_loss, now)

    ts = now_ts()
    pid = new_id()
    record = {
        "id": pid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "claim_id": claim_id,
        "documented_building_loss": documented_building_loss,
        "documented_contents_loss": documented_contents_loss,
        "filed_at": format_iso8601_ms(now),
        "days_after_loss": days_after_loss,
        "review_status": "PENDING",
    }
    db.proofs_of_loss[pid] = record
    return success(serialize_proof_of_loss(record), status=201)


@bp.route("/proofs-of-loss/<pid>", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def get_proof(pid):
    record = db.proofs_of_loss.get(pid)
    if record is None:
        raise errors.not_found("Proof-of-loss not found")
    if g.user_role == "PolicyHolder":
        claim = db.claims.get(record["claim_id"])
        if claim is not None and claim["claimant_id"] != g.user_id:
            raise errors.not_resource_owner("Not the claimant of this proof's claim")
    return success(serialize_proof_of_loss(record), status=200)


@bp.route("/proofs-of-loss/<pid>/accept", methods=["POST"])
@require_roles("Adjuster")
def accept_proof(pid):
    record = db.proofs_of_loss.get(pid)
    if record is None:
        raise errors.not_found("Proof-of-loss not found")

    # State (priority 5): proof must be PENDING and its claim UNDER_REVIEW.
    if record["review_status"] != "PENDING":
        raise errors.invalid_state("Proof-of-loss must be PENDING to accept")
    claim = db.claims.get(record["claim_id"])
    if claim is None or claim["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Supported claim must be UNDER_REVIEW")

    # Timeliness (priority 12): days_after_loss <= 60 (inclusive).
    if record["days_after_loss"] > PROOF_OF_LOSS_DEADLINE_DAYS:
        raise errors.ApiError(errors.ERR_PROOF_OF_LOSS_LATE, 409,
                              "Proof-of-loss filed after the 60-day deadline")

    # Reconciliation (priority 15): sworn figures must equal the claim's losses.
    documented = record["documented_building_loss"] + record["documented_contents_loss"]
    reported = claim["building_loss"] + claim["contents_loss"]
    if documented != reported:
        raise errors.ApiError(errors.ERR_PROOF_OF_LOSS_MISMATCH, 422,
                              "Sworn loss figures do not reconcile with the claim")

    record["review_status"] = "ACCEPTED"
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_proof_of_loss(record), status=200)


@bp.route("/proofs-of-loss/<pid>/reject", methods=["POST"])
@require_roles("Adjuster")
def reject_proof(pid):
    record = db.proofs_of_loss.get(pid)
    if record is None:
        raise errors.not_found("Proof-of-loss not found")

    # State (priority 5): proof must be PENDING.
    if record["review_status"] != "PENDING":
        raise errors.invalid_state("Proof-of-loss must be PENDING to reject")

    record["review_status"] = "REJECTED"
    record["version"] += 1
    record["updated_at"] = now_ts()

    # Bounce the supported claim back to SUBMITTED if it is UNDER_REVIEW.
    claim = db.claims.get(record["claim_id"])
    if claim is not None and claim["status"] == "UNDER_REVIEW":
        claim["status"] = "SUBMITTED"
        claim["version"] += 1
        claim["updated_at"] = now_ts()

    return success(serialize_proof_of_loss(record), status=200)
