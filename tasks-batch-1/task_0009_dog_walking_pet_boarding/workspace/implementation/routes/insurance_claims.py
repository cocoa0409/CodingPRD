"""InsuranceClaim routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_APPROVED_AMOUNT,
)
from middleware import require_auth
from services.calculations import compute_claim_payout
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    optional_str,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sorted_by_created_at,
)
from services.lookup import (
    fk_booking,
    get_insurance_claim_or_404,
)
from services.sitter_logic import cascade2_claim_paid

bp = Blueprint("insurance_claims", __name__)


_CLAIM_STATUSES = {
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "PAID",
    "DENIED",
    "WITHDRAWN",
}


def claim_to_dict(c: dict) -> dict:
    return {
        "id": c["id"],
        "booking_id": c["booking_id"],
        "sitter_id_snapshot": c["sitter_id_snapshot"],
        "sitter_tier_snapshot": c["sitter_tier_snapshot"],
        "claim_amount_cents": c["claim_amount_cents"],
        "approved_amount_cents": c["approved_amount_cents"],
        "status": c["status"],
        "provisional_payout_cents": c["provisional_payout_cents"],
        "final_payout_cents": c["final_payout_cents"],
        "adjuster_notes": c["adjuster_notes"],
        "denied_reason": c["denied_reason"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/api/v1/insurance-claims")
@require_auth(roles=["Owner"])
def create_claim():
    body = get_json_body()
    booking_id = require_str(body, "booking_id")
    claim_amount_cents = require_int(body, "claim_amount_cents")
    adjuster_notes = optional_str(body, "adjuster_notes", "")

    if claim_amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "claim_amount_cents must be > 0.")

    booking = fk_booking(booking_id)
    if booking["status"] not in ("IN_PROGRESS", "COMPLETED", "EMERGENCY_TERMINATED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Booking must be IN_PROGRESS, COMPLETED, or EMERGENCY_TERMINATED.",
        )

    sitter = db.sitters.get(booking["sitter_id"])
    sitter_tier_snapshot = sitter["tier"] if sitter else "BRONZE"

    provisional = compute_claim_payout(
        amount_cents=claim_amount_cents,
        sitter_tier_snapshot=sitter_tier_snapshot,
    )

    with db.lock:
        c = {
            **new_common_fields(),
            "booking_id": booking_id,
            "sitter_id_snapshot": booking["sitter_id"],
            "sitter_tier_snapshot": sitter_tier_snapshot,
            "claim_amount_cents": claim_amount_cents,
            "approved_amount_cents": None,
            "status": "SUBMITTED",
            "provisional_payout_cents": provisional,
            "final_payout_cents": 0,
            "adjuster_notes": adjuster_notes,
            "denied_reason": None,
        }
        db.insurance_claims[c["id"]] = c
    return response.ok(claim_to_dict(c), status=201)


@bp.get("/api/v1/insurance-claims/<cid>")
@require_auth(roles=["Owner", "ClaimsAdjuster", "PlatformAdmin"])
def get_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    return response.ok(claim_to_dict(c))


@bp.get("/api/v1/insurance-claims")
@require_auth(roles=["Owner", "ClaimsAdjuster", "PlatformAdmin"])
def list_claims():
    limit, offset = parse_pagination()
    booking_id = request.args.get("booking_id")
    sitter_id_snapshot = request.args.get("sitter_id_snapshot")
    status_filter = request.args.get("status")

    items = list(db.insurance_claims.values())
    if booking_id is not None:
        items = [c for c in items if c["booking_id"] == booking_id]
    if sitter_id_snapshot is not None:
        items = [c for c in items if c["sitter_id_snapshot"] == sitter_id_snapshot]
    if status_filter is not None:
        if status_filter not in _CLAIM_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, f"Invalid status filter: {status_filter}")
        items = [c for c in items if c["status"] == status_filter]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([claim_to_dict(c) for c in page], limit, offset, total)


@bp.post("/api/v1/insurance-claims/<cid>/start-review")
@require_auth(roles=["ClaimsAdjuster"])
def start_review_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Claim must be SUBMITTED to start review.")
    with db.lock:
        c["status"] = "UNDER_REVIEW"
        bump(c)
    return response.ok(claim_to_dict(c))


@bp.post("/api/v1/insurance-claims/<cid>/approve")
@require_auth(roles=["ClaimsAdjuster"])
def approve_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Claim must be UNDER_REVIEW to approve.")
    body = get_json_body()
    approved_amount_cents = require_int(body, "approved_amount_cents")
    adjuster_notes = optional_str(body, "adjuster_notes", c.get("adjuster_notes", ""))

    if approved_amount_cents <= 0 or approved_amount_cents > c["claim_amount_cents"]:
        raise ApiError(
            ERR_INVALID_APPROVED_AMOUNT,
            "approved_amount_cents must satisfy 0 < amount <= claim_amount_cents.",
        )

    final = compute_claim_payout(
        amount_cents=approved_amount_cents,
        sitter_tier_snapshot=c["sitter_tier_snapshot"],
    )
    with db.lock:
        c["approved_amount_cents"] = approved_amount_cents
        c["adjuster_notes"] = adjuster_notes
        c["final_payout_cents"] = final
        c["status"] = "APPROVED"
        bump(c)
    return response.ok(claim_to_dict(c))


@bp.post("/api/v1/insurance-claims/<cid>/revert")
@require_auth(roles=["ClaimsAdjuster"])
def revert_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    body = get_json_body()
    adjuster_notes = body.get("adjuster_notes")

    if c["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Claim must be APPROVED to revert.")
    if adjuster_notes is not None and not isinstance(adjuster_notes, str):
        raise ApiError(ERR_INVALID_REQUEST, "adjuster_notes must be a string.")
    with db.lock:
        c["status"] = "UNDER_REVIEW"
        c["approved_amount_cents"] = None
        c["final_payout_cents"] = 0
        if adjuster_notes is not None:
            c["adjuster_notes"] = adjuster_notes
        bump(c)
    return response.ok(claim_to_dict(c))


@bp.post("/api/v1/insurance-claims/<cid>/pay")
@require_auth(roles=["ClaimsAdjuster"])
def pay_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    if c["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Claim must be APPROVED to pay.")
    with db.lock:
        c["status"] = "PAID"
        bump(c)
        # Cascade #2
        sitter = db.sitters.get(c["sitter_id_snapshot"])
        if sitter is not None:
            cascade2_claim_paid(sitter)
    return response.ok(claim_to_dict(c))


@bp.post("/api/v1/insurance-claims/<cid>/deny")
@require_auth(roles=["ClaimsAdjuster"])
def deny_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, "Claim must be UNDER_REVIEW to deny.")
    body = get_json_body()
    denied_reason = require_str(body, "denied_reason")
    adjuster_notes = optional_str(body, "adjuster_notes", c.get("adjuster_notes", ""))
    with db.lock:
        c["denied_reason"] = denied_reason
        c["adjuster_notes"] = adjuster_notes
        c["status"] = "DENIED"
        bump(c)
    return response.ok(claim_to_dict(c))


@bp.post("/api/v1/insurance-claims/<cid>/withdraw")
@require_auth(roles=["Owner"])
def withdraw_claim(cid: str):
    c = get_insurance_claim_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Claim must be SUBMITTED to withdraw.")
    with db.lock:
        c["status"] = "WITHDRAWN"
        bump(c)
    return response.ok(claim_to_dict(c))
