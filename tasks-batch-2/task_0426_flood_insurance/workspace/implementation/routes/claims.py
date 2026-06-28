"""Claim endpoints: file, get, list, and the review lifecycle open-review /
approve / deny, plus the per-claim proof-of-loss list (PRD §3.8, §3.10).
"""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from clock import parse_iso8601
from middleware import require_roles
from response import success, list_success
from serializers import serialize_claim, serialize_proof_of_loss
from helpers import (
    get_body, require_str, require_number, opt_number, opt_bool, require_int,
    parse_pagination, paginate, sort_by_created,
)
from services.calculations import compute_settlement

bp = Blueprint("claims", __name__)


@bp.route("/claims", methods=["POST"])
@require_roles("PolicyHolder")
def file_claim():
    body = get_body()
    policy_id = require_str(body, "policy_id")
    claimant_id = require_str(body, "claimant_id")
    date_of_loss_raw = require_str(body, "date_of_loss")
    try:
        date_of_loss = parse_iso8601(date_of_loss_raw)
    except (ValueError, TypeError):
        raise errors.validation("date_of_loss must be a valid ISO 8601 instant")

    building_loss = opt_number(body, "building_loss", 0)
    contents_loss = opt_number(body, "contents_loss", 0)
    depreciation_pct = opt_number(body, "depreciation_pct", 0)
    substantial_damage = opt_bool(body, "substantial_damage", False)
    icc_eligible_cost = opt_number(body, "icc_eligible_cost", 0)

    if depreciation_pct < 0 or depreciation_pct >= 1:
        raise errors.validation("depreciation_pct must satisfy 0 <= depreciation_pct < 1")

    # Existence (priority 3): policy_id FK must resolve.
    policy = db.policies.get(policy_id)
    if policy is None:
        raise errors.not_found("Policy not found")

    # Ownership (priority 4): claimant must be the acting holder and the policy holder.
    if claimant_id != g.user_id:
        raise errors.not_resource_owner("claimant_id must equal the acting PolicyHolder")
    if policy["holder_id"] != g.user_id:
        raise errors.not_resource_owner("Acting PolicyHolder does not hold this policy")

    ts = now_ts()
    cid = new_id()
    record = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "policy_id": policy_id,
        "claimant_id": claimant_id,
        "date_of_loss": date_of_loss_raw,
        "building_loss": building_loss,
        "contents_loss": contents_loss,
        "depreciation_pct": depreciation_pct,
        "substantial_damage": substantial_damage,
        "icc_eligible_cost": icc_eligible_cost,
        "status": "SUBMITTED",
        "settlement_total": 0,
        "building_payable": 0,
        "contents_payable": 0,
        "icc_payable": 0,
    }
    db.claims[cid] = record
    return success(serialize_claim(record), status=201)


@bp.route("/claims/<cid>", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def get_claim(cid):
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")
    if g.user_role == "PolicyHolder" and record["claimant_id"] != g.user_id:
        raise errors.not_resource_owner("Not the claimant of this claim")
    return success(serialize_claim(record), status=200)


@bp.route("/claims", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def list_claims():
    limit, offset = parse_pagination()
    policy_id = request.args.get("policy_id")

    items = list(db.claims.values())
    if policy_id is not None:
        items = [c for c in items if c["policy_id"] == policy_id]
    if g.user_role == "PolicyHolder":
        items = [c for c in items if c["claimant_id"] == g.user_id]

    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/claims/<cid>/open-review", methods=["POST"])
@require_roles("Adjuster")
def open_review(cid):
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")

    # State (priority 5): only SUBMITTED -> UNDER_REVIEW.
    if record["status"] != "SUBMITTED":
        raise errors.invalid_state("Claim must be SUBMITTED to open review")

    policy = db.policies.get(record["policy_id"])

    # Policy must be ACTIVE (priority 10).
    if policy["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_POLICY_NOT_ACTIVE, 409,
                              "Claim's policy is not ACTIVE")

    # Loss within coverage window [effective_date, expiration_date) (priority 11).
    loss = parse_iso8601(record["date_of_loss"])
    effective = parse_iso8601(policy["effective_date"])
    expiration = parse_iso8601(policy["expiration_date"])
    if loss < effective or loss >= expiration:
        raise errors.ApiError(errors.ERR_LOSS_OUTSIDE_COVERAGE, 409,
                              "date_of_loss is outside the coverage window")

    record["status"] = "UNDER_REVIEW"
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_claim(record), status=200)


@bp.route("/claims/<cid>/approve", methods=["POST"])
@require_roles("Adjuster")
def approve_claim(cid):
    body = get_body()
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")

    # State (priority 5): only UNDER_REVIEW -> APPROVED.
    if record["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim must be UNDER_REVIEW to approve")

    # An ACCEPTED proof-of-loss must exist (priority 13).
    has_accepted = any(
        p["claim_id"] == cid and p["review_status"] == "ACCEPTED"
        for p in db.proofs_of_loss.values()
    )
    if not has_accepted:
        raise errors.ApiError(errors.ERR_PROOF_OF_LOSS_MISSING, 409,
                              "No ACCEPTED proof-of-loss exists for this claim")

    # ICC eligibility (priority 14): icc_eligible_cost > 0 without substantial_damage.
    if record["icc_eligible_cost"] > 0 and not record["substantial_damage"]:
        raise errors.ApiError(errors.ERR_ICC_NOT_ELIGIBLE, 422,
                              "ICC requires substantial_damage to be true")

    # OCC (priority 16): expected_claim_version must match live version.
    expected = require_int(body, "expected_claim_version")
    if expected != record["version"]:
        raise errors.ApiError(errors.ERR_STALE_CLAIM_VERSION, 412,
                              "expected_claim_version does not match live version")

    policy = db.policies.get(record["policy_id"])
    prop = db.properties.get(policy["property_id"])

    settlement = compute_settlement(
        prop["occupancy"],
        record["building_loss"],
        record["contents_loss"],
        record["depreciation_pct"],
        policy["building_coverage"],
        policy["contents_coverage"],
        policy["building_deductible"],
        policy["contents_deductible"],
        record["substantial_damage"],
        record["icc_eligible_cost"],
    )

    record["building_payable"] = settlement["building_payable"]
    record["contents_payable"] = settlement["contents_payable"]
    record["icc_payable"] = settlement["icc_payable"]
    record["settlement_total"] = settlement["settlement_total"]
    record["status"] = "APPROVED"
    record["version"] += 1
    record["updated_at"] = now_ts()

    # Ledger cascade: policy total_claims_paid, property loss tally + repetitive flag.
    policy["total_claims_paid"] += settlement["settlement_total"]
    policy["version"] += 1
    policy["updated_at"] = now_ts()

    prop["loss_history_count"] += 1
    if prop["loss_history_count"] >= 2:
        prop["is_repetitive_loss"] = True
    prop["version"] += 1
    prop["updated_at"] = now_ts()

    return success(serialize_claim(record), status=200)


@bp.route("/claims/<cid>/deny", methods=["POST"])
@require_roles("Adjuster")
def deny_claim(cid):
    body = get_body()
    record = db.claims.get(cid)
    if record is None:
        raise errors.not_found("Claim not found")

    # State (priority 5): only UNDER_REVIEW -> DENIED.
    if record["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Claim must be UNDER_REVIEW to deny")

    # OCC (priority 16): expected_claim_version must match live version.
    expected = require_int(body, "expected_claim_version")
    if expected != record["version"]:
        raise errors.ApiError(errors.ERR_STALE_CLAIM_VERSION, 412,
                              "expected_claim_version does not match live version")

    record["status"] = "DENIED"
    record["version"] += 1
    record["updated_at"] = now_ts()
    return success(serialize_claim(record), status=200)


@bp.route("/claims/<cid>/proofs-of-loss", methods=["GET"])
@require_roles("PolicyHolder", "Underwriter", "Adjuster", "FemaAdmin")
def list_claim_proofs(cid):
    claim = db.claims.get(cid)
    if claim is None:
        raise errors.not_found("Claim not found")
    if g.user_role == "PolicyHolder" and claim["claimant_id"] != g.user_id:
        raise errors.not_resource_owner("Not the claimant of this claim")
    limit, offset = parse_pagination()
    items = [p for p in db.proofs_of_loss.values() if p["claim_id"] == cid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_proof_of_loss(p) for p in page], limit, offset, total)
