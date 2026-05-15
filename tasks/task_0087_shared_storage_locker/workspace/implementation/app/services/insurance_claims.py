"""Insurance claim business logic (PRD §3.9)."""
from __future__ import annotations

from typing import Any, Optional

from .. import constants
from ..auth import current_actor
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store, new_id
from .rentals import get_rental_or_404
from .serializers import serialize_insurance_claim
from .validation import (
    require_field,
    require_in,
    require_int,
    require_str,
)


def get_claim_or_404(claim_id: str) -> dict[str, Any]:
    store = get_store()
    c = store.insurance_claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", f"InsuranceClaim {claim_id} not found.")
    return c


def _check_version(entity: dict[str, Any], supplied: Any) -> None:
    if supplied is None:
        return
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise ApiError("ERR_BAD_REQUEST", "version must be an integer.")
    if supplied != int(entity.get("version", 0)):
        raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


def _ownership_check(claim: dict[str, Any]) -> tuple[str, str]:
    actor_id, actor_role = current_actor()
    if actor_role == "Renter" and claim["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own this claim.")
    return actor_id, actor_role


def create_claim(body: dict[str, Any]) -> dict[str, Any]:
    rental_id = require_str(require_field(body, "rental_id"), "rental_id")
    claim_type = require_in(require_field(body, "claim_type"), "claim_type", constants.CLAIM_TYPES)
    claimed_amount_cents = require_int(
        require_field(body, "claimed_amount_cents"), "claimed_amount_cents", min_value=1
    )

    rental = get_rental_or_404(rental_id)
    actor_id, actor_role = current_actor()
    if actor_role == "Renter" and rental["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own the rental.")

    store = get_store()
    # Uniqueness: only one claim in non-terminal status
    for existing in store.insurance_claims.values():
        if existing["rental_id"] == rental_id and existing["status"] not in ("DENIED", "PAID"):
            raise ApiError("ERR_CLAIM_ALREADY_OPEN", "An open claim already exists for this rental.")

    claim = common_fields_create()
    claim.update(
        {
            "rental_id": rental_id,
            "renter_id": rental["renter_id"],
            "claim_type": claim_type,
            "claimed_amount_cents": claimed_amount_cents,
            "evidence_count": 0,
            "status": "REPORTED",
            "payout_cents": None,
            "insurer_reference": None,
            "rejection_reason": None,
        }
    )
    store.insurance_claims[claim["id"]] = claim
    return serialize_insurance_claim(claim)


def get_claim(claim_id: str) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    actor_id, actor_role = current_actor()
    if actor_role == "Renter" and claim["renter_id"] != actor_id:
        raise ApiError("ERR_FORBIDDEN", "Renter does not own this claim.")
    return serialize_insurance_claim(claim)


def request_evidence(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _check_version(claim, body.get("version"))
    if claim["status"] not in ("REPORTED", "EVIDENCE_REJECTED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot request evidence in status {claim['status']}.")

    # Verify Rental.insurance_tier is BASIC or PREMIUM
    rental = get_rental_or_404(claim["rental_id"])
    if rental["insurance_tier"] not in ("BASIC", "PREMIUM"):
        raise ApiError("ERR_INVALID_INSURANCE", "Rental does not have insurance.")

    claim["status"] = "EVIDENCE_PENDING"
    bump_version(claim)
    return serialize_insurance_claim(claim)


def submit_evidence(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _ownership_check(claim)
    _check_version(claim, body.get("version"))
    if claim["status"] != "EVIDENCE_PENDING":
        raise ApiError("ERR_INVALID_STATE", f"Cannot submit evidence in status {claim['status']}.")
    require_str(require_field(body, "evidence_description"), "evidence_description")
    claim["evidence_count"] = int(claim["evidence_count"]) + 1
    claim["status"] = "UNDER_REVIEW"
    if not claim.get("insurer_reference"):
        claim["insurer_reference"] = f"INS-{new_id()}"
    bump_version(claim)
    return serialize_insurance_claim(claim)


def reject_evidence(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _check_version(claim, body.get("version"))
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", f"Cannot reject evidence in status {claim['status']}.")
    rejection_reason = require_str(require_field(body, "rejection_reason"), "rejection_reason")
    claim["rejection_reason"] = rejection_reason
    claim["status"] = "EVIDENCE_REJECTED"
    bump_version(claim)
    return serialize_insurance_claim(claim)


def approve_claim(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _check_version(claim, body.get("version"))
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", f"Cannot approve in status {claim['status']}.")
    payout_cents = require_int(require_field(body, "payout_cents"), "payout_cents", min_value=0)

    rental = get_rental_or_404(claim["rental_id"])
    tier = rental.get("insurance_tier")
    if tier not in ("BASIC", "PREMIUM"):
        raise ApiError("ERR_PAYOUT_EXCEEDS_CAP", "Rental has no insurance tier.")
    tier_cap = constants.TIER_PAYOUT_CAP.get(tier, 0)
    cap = min(
        int(claim["claimed_amount_cents"]),
        int(rental["declared_value_cents"]),
        int(tier_cap),
    )
    if payout_cents > cap:
        raise ApiError("ERR_PAYOUT_EXCEEDS_CAP", f"payout_cents {payout_cents} exceeds cap {cap}.")
    claim["payout_cents"] = payout_cents
    claim["status"] = "APPROVED"
    bump_version(claim)
    return serialize_insurance_claim(claim)


def deny_claim(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _check_version(claim, body.get("version"))
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", f"Cannot deny in status {claim['status']}.")
    rejection_reason = require_str(require_field(body, "rejection_reason"), "rejection_reason")
    claim["rejection_reason"] = rejection_reason
    claim["status"] = "DENIED"
    bump_version(claim)
    return serialize_insurance_claim(claim)


def pay_claim(claim_id: str, body: dict[str, Any]) -> dict[str, Any]:
    claim = get_claim_or_404(claim_id)
    _check_version(claim, body.get("version"))
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot pay in status {claim['status']}.")
    claim["status"] = "PAID"
    bump_version(claim)
    return serialize_insurance_claim(claim)
