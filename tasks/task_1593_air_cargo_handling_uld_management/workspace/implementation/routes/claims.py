"""Claim endpoints (PRD 3.9): filing (owner only, booking LOADED),
adjudication with the pinned per-item-rounding settlement calculation,
and settlement."""

from flask import Blueprint

import db
import serializers
import services
from envelope import success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_BOOKING_NOT_OWNED,
    ERR_BOOKING_INVALID_STATE,
    ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_NOT_APPROVED,
)
from middleware import require_roles, ALL_ROLES
from util import (
    get_json_body,
    is_number,
    optional_string,
    require_enum,
    require_number,
    require_string,
)

bp = Blueprint("claims", __name__)


def get_claim_or_404(claim_id: str) -> dict:
    claim = db.claims.get(claim_id)
    if claim is None:
        raise_err(ERR_NOT_FOUND, f"Claim {claim_id} not found")
    return claim


@bp.route("/claims", methods=["POST"])
@require_roles("ForwarderAgent")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()
    # rung 3: booking referenced in the body must exist
    booking_ref = body.get("booking_id")
    if booking_ref is not None and booking_ref not in db.bookings:
        raise_err(ERR_NOT_FOUND, f"Booking {booking_ref} not found")
    # rung 4: shape
    booking_id = require_string(body, "booking_id")
    claim_type = require_enum(body, "claim_type", ("DAMAGE", "LOSS"))
    claimed_amount = require_number(body, "claimed_amount")
    if services.dec(claimed_amount) <= 0:
        raise_err(ERR_INVALID_REQUEST, "claimed_amount must be greater than 0")
    items = body.get("items")
    if not isinstance(items, list) or len(items) == 0:
        raise_err(ERR_INVALID_REQUEST, "items must be a non-empty list")
    for item in items:
        if not isinstance(item, dict) or not is_number(item.get("weight_kg")):
            raise_err(ERR_INVALID_REQUEST, "each item must carry a numeric weight_kg")
        if services.dec(item["weight_kg"]) <= 0:
            raise_err(ERR_INVALID_REQUEST, "each item's weight_kg must be greater than 0")
    description = optional_string(body, "description")

    booking = db.bookings[booking_id]
    # rung 5: ownership (attribute authorization precedes state)
    if booking["created_by_user_id"] != _user_id:
        raise_err(ERR_BOOKING_NOT_OWNED, "Booking is owned by another forwarder")
    # rung 6: the booking must have flown
    if booking["status"] != "LOADED":
        raise_err(ERR_BOOKING_INVALID_STATE, "Claim requires booking LOADED")

    claim = {
        "booking_id": booking_id,
        "claim_type": claim_type,
        "claimed_amount": claimed_amount,
        "items": items,
        "description": description,
        "item_total": None,
        "basis": None,
        "approved_amount": None,
        "settlement_ref": None,
        "status": "SUBMITTED",
    }
    db.stamp_new(claim)
    db.claims[claim["id"]] = claim
    return success_object(serializers.claim(claim), 201)


@bp.route("/claims/<claim_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_claim(claim_id: str, _user_id: str, _role: str):
    return success_object(serializers.claim(get_claim_or_404(claim_id)))


@bp.route("/claims/<claim_id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_SUBMITTED, "Approve requires claim SUBMITTED")
    booking = db.bookings[claim["booking_id"]]
    item_total, basis, approved_amount = services.claim_settlement(claim, booking)
    claim["item_total"] = item_total
    claim["basis"] = basis
    claim["approved_amount"] = approved_amount
    claim["status"] = "APPROVED"
    db.touch(claim)
    return success_object(serializers.claim(claim))


@bp.route("/claims/<claim_id>/reject", methods=["POST"])
@require_roles("ClaimsAdjuster")
def reject_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    body = get_json_body()
    require_string(body, "reason")  # mandatory; not persisted on the resource
    if claim["status"] != "SUBMITTED":
        raise_err(ERR_CLAIM_NOT_SUBMITTED, "Reject requires claim SUBMITTED")
    claim["status"] = "REJECTED"
    db.touch(claim)
    return success_object(serializers.claim(claim))


@bp.route("/claims/<claim_id>/settle", methods=["POST"])
@require_roles("ClaimsAdjuster")
def settle_claim(claim_id: str, _user_id: str, _role: str):
    claim = get_claim_or_404(claim_id)
    body = get_json_body()
    settlement_ref = require_string(body, "settlement_ref")
    if claim["status"] != "APPROVED":
        raise_err(ERR_CLAIM_NOT_APPROVED, "Settle requires claim APPROVED")
    claim["settlement_ref"] = settlement_ref
    claim["status"] = "SETTLED"
    db.touch(claim)
    return success_object(serializers.claim(claim))
