"""Dispute endpoints per PRD 3.6."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    check_provider_owner,
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services import core
from services.calc import DECISION_DEADLINE_DAYS, DISPUTE_WINDOW_DAYS

bp = Blueprint("disputes", __name__)
PREFIX = "/payment-integrity"

DISPUTE_STATUSES = {"SUBMITTED", "UNDER_REVIEW", "AWAITING_PROVIDER_INFO", "DECIDED"}


@bp.route(PREFIX + "/claims/<cid>/disputes", methods=["POST"])
def create_dispute(cid):
    user_id, role = require_auth()
    require_role(role, ["Provider"])
    body = get_body()
    # Band 4 shape
    vals = validate_body(
        body,
        {
            "edit_hit_id": (True, "string", None),
            "reason": (True, "string", None),
            "expected_claim_version": (True, "integer", None),
        },
    )
    # Band 5 existence, left to right: claim, then edit hit (body reference)
    claim = db.get("claims", cid)
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "Claim not found")
    hit = db.get("edit_hits", vals["edit_hit_id"])
    if hit is None:
        raise_err("ERR_EDIT_HIT_NOT_FOUND", "Edit hit not found")
    # Band 3 ownership: caller is the claim's provider
    check_provider_owner(user_id, claim["provider_id"])
    # Band 6 OCC on Claim.version
    if vals["expected_claim_version"] != claim["version"]:
        raise_err("ERR_STALE_VERSION", "Stale claim version; re-read before disputing")
    # Band 7 state: claim finalized and hit CONFIRMED
    if claim["status"] not in ("DETERMINED", "READY_TO_PAY", "DENIED", "PAID"):
        raise_err("ERR_DISPUTE_NOT_OPEN", "Claim not finalized")
    if hit["status"] != "CONFIRMED":
        raise_err("ERR_DISPUTE_NOT_OPEN", "Hit is not CONFIRMED")
    # Band 9: at most one non-DECIDED dispute per hit
    for d in db.all_records("disputes"):
        if d["edit_hit_id"] == hit["id"] and d["status"] != "DECIDED":
            raise_err("ERR_DISPUTE_ALREADY_OPEN", "A non-DECIDED dispute exists for this hit")
    # Band 10 temporal: dispute window 45 days inclusive from determined_at
    now = db.now()
    determined_at = claim.get("determined_at")
    if determined_at is None or now > determined_at + timedelta(days=DISPUTE_WINDOW_DAYS):
        raise_err("ERR_DISPUTE_WINDOW_EXPIRED", "Dispute window has expired")
    # Band 11 referential: hit must belong to the path claim
    if hit["claim_id"] != cid:
        raise_err("ERR_HIT_NOT_ON_CLAIM", "edit_hit_id does not belong to the path claim")
    dispute = db.create_resource(
        "disputes",
        {
            "claim_id": cid,
            "edit_hit_id": hit["id"],
            "provider_id": claim["provider_id"],
            "reason": vals["reason"],
            "status": "SUBMITTED",
            "outcome": None,
            "released_cents": 0,
            "submitted_at": now,
            "decided_at": None,
            "adjudicated_by_user_id": None,
        },
    )
    db.touch(claim)  # creation increments the claim's version by one
    return success_object(serialize(dispute), status=201)


@bp.route(PREFIX + "/disputes", methods=["GET"])
def list_disputes():
    require_auth()
    limit, offset = pagination_params()
    claim_id = request.args.get("claim_id")
    edit_hit_id = request.args.get("edit_hit_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    rows = db.all_records("disputes")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if edit_hit_id is not None:
        rows = [r for r in rows if r["edit_hit_id"] == edit_hit_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        if status not in DISPUTE_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_dispute_or_404(did):
    dispute = db.get("disputes", did)
    if dispute is None:
        raise_err("ERR_DISPUTE_NOT_FOUND", "Dispute not found")
    return dispute


@bp.route(PREFIX + "/disputes/<did>", methods=["GET"])
def get_dispute(did):
    require_auth()
    return success_object(serialize(_get_dispute_or_404(did)))


@bp.route(PREFIX + "/disputes/<did>/start-review", methods=["POST"])
def start_review(did):
    user_id, role = require_auth()
    require_role(role, ["DisputeAdjudicator"])
    body = get_body()
    validate_body(body, {})
    dispute = _get_dispute_or_404(did)
    if dispute["status"] != "SUBMITTED":
        raise_err("ERR_DISPUTE_NOT_DECIDABLE", "start-review requires SUBMITTED")
    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)
    return success_object(serialize(dispute))


@bp.route(PREFIX + "/disputes/<did>/request-info", methods=["POST"])
def request_info(did):
    user_id, role = require_auth()
    require_role(role, ["DisputeAdjudicator"])
    body = get_body()
    validate_body(body, {"info_request_note": (False, "string", None)})
    dispute = _get_dispute_or_404(did)
    if dispute["status"] != "UNDER_REVIEW":
        raise_err("ERR_DISPUTE_NOT_DECIDABLE", "request-info requires UNDER_REVIEW")
    dispute["status"] = "AWAITING_PROVIDER_INFO"
    db.touch(dispute)
    return success_object(serialize(dispute))


@bp.route(PREFIX + "/disputes/<did>/submit-info", methods=["POST"])
def submit_info(did):
    user_id, role = require_auth()
    require_role(role, ["Provider"])
    body = get_body()
    validate_body(body, {"info_response": (False, "string", None)})
    dispute = _get_dispute_or_404(did)
    if dispute["status"] != "AWAITING_PROVIDER_INFO":
        raise_err("ERR_DISPUTE_NOT_DECIDABLE", "submit-info requires AWAITING_PROVIDER_INFO")
    # Ownership: only the dispute's own provider returns info
    check_provider_owner(user_id, dispute["provider_id"])
    dispute["status"] = "UNDER_REVIEW"
    db.touch(dispute)
    return success_object(serialize(dispute))


@bp.route(PREFIX + "/disputes/<did>/decide", methods=["POST"])
def decide_dispute(did):
    user_id, role = require_auth()
    require_role(role, ["DisputeAdjudicator"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "outcome": (True, "string", {"UPHELD", "OVERTURNED", "PARTIAL"}),
            "released_cents": (False, "integer", None),
            "decision_note": (False, "string", None),
        },
    )
    dispute = _get_dispute_or_404(did)
    hit = db.get("edit_hits", dispute["edit_hit_id"])
    # Guard surfacing order per PRD 3.6: state -> SoD -> deadline -> release bounds
    if dispute["status"] != "UNDER_REVIEW":
        raise_err("ERR_DISPUTE_NOT_DECIDABLE", "decide requires UNDER_REVIEW")
    if hit is not None and user_id == hit.get("confirmed_by_user_id"):
        raise_err("ERR_SOD_REVIEWER_ADJUDICATION", "Adjudicator may not decide a hit they confirmed")
    now = db.now()
    if now > dispute["submitted_at"] + timedelta(days=DECISION_DEADLINE_DAYS):
        raise_err("ERR_DECISION_DEADLINE_PASSED", "Decision deadline passed")
    outcome = vals["outcome"]
    released = vals.get("released_cents", 0) or 0
    if outcome == "PARTIAL":
        if hit is None or not (0 < released <= hit["attributed_savings_cents"]):
            raise_err("ERR_INVALID_RELEASE_AMOUNT", "PARTIAL requires 0 < released_cents <= attributed")
    dispute["status"] = "DECIDED"
    dispute["outcome"] = outcome
    dispute["released_cents"] = released if outcome == "PARTIAL" else 0
    dispute["decided_at"] = now
    dispute["adjudicated_by_user_id"] = user_id
    db.touch(dispute)
    if hit is not None and hit["status"] == "CONFIRMED":
        if outcome == "OVERTURNED":
            core.resolve_hit_false_positive(hit)
        elif outcome == "PARTIAL":
            core.resolve_hit_override(hit, released)
        else:  # UPHELD — no hit or amount changes; still bump claim version
            claim = db.get("claims", dispute["claim_id"])
            if claim is not None:
                db.touch(claim)
    return success_object(serialize(dispute))
