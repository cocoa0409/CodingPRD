"""ItemizedBillReview endpoints per PRD 3.7."""

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
from services.calc import IBR_DOCUMENTS_DUE_DAYS, itemized_reprice

bp = Blueprint("ibr", __name__)
PREFIX = "/payment-integrity"

IBR_STATUSES = {"REQUESTED", "DOCUMENTS_RECEIVED", "IN_AUDIT", "COMPLETED", "EXPIRED"}


@bp.route(PREFIX + "/claims/<cid>/itemized-bill-reviews", methods=["POST"])
def create_ibr(cid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    validate_body(body, {})
    claim = db.get("claims", cid)
    if claim is None:
        raise_err("ERR_CLAIM_NOT_FOUND", "Claim not found")
    # Band 10 temporal: provider occupancy rule
    now = db.now()
    if core.provider_ibr_overlap(claim["provider_id"], now):
        raise_err("ERR_PROVIDER_AUDIT_OVERLAP", "Provider has an overlapping audit interval")
    ibr = db.create_resource(
        "ibrs",
        {
            "claim_id": cid,
            "provider_id": claim["provider_id"],
            "status": "REQUESTED",
            "requested_at": now,
            "due_at": now + timedelta(days=IBR_DOCUMENTS_DUE_DAYS),
            "completed_at": None,
            "findings_cents": 0,
            "repriced_total_cents": None,
            "auditor_user_id": None,
        },
    )
    core.recompute_abrasion(claim["provider_id"])
    # A manual IBR on a READY_TO_PAY claim reopens it to PENDED
    if claim["status"] == "READY_TO_PAY":
        claim["status"] = "PENDED"
        db.touch(claim)
    return success_object(serialize(ibr), status=201)


@bp.route(PREFIX + "/itemized-bill-reviews", methods=["GET"])
def list_ibrs():
    require_auth()
    limit, offset = pagination_params()
    claim_id = request.args.get("claim_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    rows = db.all_records("ibrs")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if provider_id is not None:
        rows = [r for r in rows if r["provider_id"] == provider_id]
    if status is not None:
        if status not in IBR_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_ibr_or_404(iid):
    ibr = db.get("ibrs", iid)
    if ibr is None:
        raise_err("ERR_IBR_NOT_FOUND", "Itemized bill review not found")
    return ibr


@bp.route(PREFIX + "/itemized-bill-reviews/<iid>", methods=["GET"])
def get_ibr(iid):
    require_auth()
    return success_object(serialize(_get_ibr_or_404(iid)))


@bp.route(PREFIX + "/itemized-bill-reviews/<iid>/receive-documents", methods=["POST"])
def receive_documents(iid):
    user_id, role = require_auth()
    require_role(role, ["Provider"])
    body = get_body()
    validate_body(body, {})
    ibr = _get_ibr_or_404(iid)
    # Ownership: the review's own provider delivers documents
    check_provider_owner(user_id, ibr["provider_id"])
    if ibr["status"] != "REQUESTED":
        raise_err("ERR_IBR_NOT_COMPLETABLE", "receive-documents requires REQUESTED")
    ibr["status"] = "DOCUMENTS_RECEIVED"
    db.touch(ibr)
    return success_object(serialize(ibr))


@bp.route(PREFIX + "/itemized-bill-reviews/<iid>/start-audit", methods=["POST"])
def start_audit(iid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    validate_body(body, {})
    ibr = _get_ibr_or_404(iid)
    if ibr["status"] != "DOCUMENTS_RECEIVED":
        raise_err("ERR_IBR_NOT_COMPLETABLE", "start-audit requires DOCUMENTS_RECEIVED")
    ibr["status"] = "IN_AUDIT"
    db.touch(ibr)
    return success_object(serialize(ibr))


@bp.route(PREFIX + "/itemized-bill-reviews/<iid>/complete", methods=["POST"])
def complete_ibr(iid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    vals = validate_body(body, {"findings_cents": (True, "integer", None)})
    if vals["findings_cents"] < 0:
        raise_err("ERR_INVALID_REQUEST", "findings_cents must be >= 0")
    ibr = _get_ibr_or_404(iid)
    if ibr["status"] != "IN_AUDIT":
        raise_err("ERR_IBR_NOT_COMPLETABLE", "complete requires IN_AUDIT")
    claim = db.get("claims", ibr["claim_id"])
    lines = [l for l in db.all_records("claim_lines") if l["claim_id"] == ibr["claim_id"]]
    repriced_total = itemized_reprice(lines)
    ibr["repriced_total_cents"] = repriced_total
    ibr["findings_cents"] = vals["findings_cents"]
    ibr["status"] = "COMPLETED"
    ibr["completed_at"] = db.now()
    ibr["auditor_user_id"] = user_id
    db.touch(ibr)
    if claim is not None:
        # allowed = max(0, min(current allowed, repriced_total)); denied rebalances
        new_allowed = min(claim["allowed_amount_cents"], repriced_total)
        if new_allowed < 0:
            new_allowed = 0
        claim["allowed_amount_cents"] = new_allowed
        claim["denied_amount_cents"] = claim["initial_allowed_cents"] - new_allowed
        db.touch(claim)
        core.recompute_abrasion(claim["provider_id"])
        core.claim_bubble_up(claim)
    return success_object(serialize(ibr))


@bp.route(PREFIX + "/itemized-bill-reviews/<iid>/expire", methods=["POST"])
def expire_ibr(iid):
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    validate_body(body, {})
    ibr = _get_ibr_or_404(iid)
    if ibr["status"] != "REQUESTED":
        raise_err("ERR_IBR_NOT_COMPLETABLE", "expire requires REQUESTED")
    now = db.now()
    if not (now > ibr["due_at"]):
        raise_err("ERR_IBR_NOT_YET_EXPIRABLE", "Review is not past its due instant")
    ibr["status"] = "EXPIRED"
    db.touch(ibr)
    claim = db.get("claims", ibr["claim_id"])
    if claim is not None:
        core.recompute_abrasion(claim["provider_id"])
        core.claim_bubble_up(claim)
    return success_object(serialize(ibr))
