"""Cargo claim endpoints (PRD section 3.14).

Claims are filed by the owning Shipper against a BOUND policy. Review and
adjudication are SoD-split (approver/denier != reviewer). Settlement follows
the coverage waterfall: DELAY excluded everywhere; FPA pays total loss only;
otherwise min(claimed, insured) - deductible.
"""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CLAIM_INVALID_STATE,
    ERR_CLAIM_NOT_FOUND,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_POLICY_INVALID_STATE,
    ERR_POLICY_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    HTTP_STATUS,
    ApiError,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import domain
from util import (
    apply_filters,
    get_json_body,
    has_field,
    optional_string,
    paginate,
    parse_pagination,
    pub,
    require_enum,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("cargo_claims", __name__)

CLAIM_TYPES = {"DAMAGE", "LOSS", "SHORTAGE", "DELAY"}


def _get_claim(claim_id: str) -> dict:
    cl = db.cargo_claims.get(claim_id)
    if cl is None:
        raise_err(ERR_CLAIM_NOT_FOUND, "CargoClaim id does not exist")
    return cl


@bp.route("/freight/claims", methods=["POST"])
@require_roles("Shipper")
def create_claim(_user_id: str, _role: str):
    body = get_json_body()

    # Band 3: policy FK existence.
    policy = None
    if has_field(body, "policy_id"):
        policy = db.insurance_policies.get(body["policy_id"])
        if policy is None:
            raise_err(ERR_POLICY_NOT_FOUND, "policy_id does not exist")

    # Band 5: body shape.
    require_string(body, "policy_id")
    claim_type = require_enum(body, "claim_type", CLAIM_TYPES)
    claimed_amount_cents = require_int(body, "claimed_amount_cents", minimum=1)
    description = optional_string(body, "description")

    # Band 2 ownership: the filing Shipper must own the policy's booking.
    booking = db.bookings.get(policy["booking_id"])
    owner_shipper_id = booking["shipper_id"] if booking else None
    if _user_id != owner_shipper_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Shipper may only file claims on its own bookings",
        )

    # Band 6: policy must be BOUND.
    if policy["status"] != "BOUND":
        raise_err(ERR_POLICY_INVALID_STATE, "Policy must be BOUND to file a claim")

    claim = {
        "policy_id": policy["id"],
        "booking_id": policy["booking_id"],
        "claim_number": f"CLM-{db.next_seq('claim')}",
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
        "description": description,
        "deductible_cents": domain.compute_deductible(
            policy["coverage_type"], policy["insured_value_cents"]
        ),
        "settlement_amount_cents": 0,
        "reviewed_by_user_id": None,
        "approved_by_user_id": None,
        "settled_at": None,
        "status": "FILED",
    }
    db.stamp_new(claim)
    db.cargo_claims[claim["id"]] = claim
    return success_object(pub(claim), 201)


@bp.route("/freight/claims", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_claims(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.cargo_claims.values()))
    items = apply_filters(items, ["policy_id", "booking_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list([pub(c) for c in page], limit, offset, total)


@bp.route("/freight/claims/<claim_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_claim(claim_id: str, _user_id: str, _role: str):
    return success_object(pub(_get_claim(claim_id)))


@bp.route("/freight/claims/<claim_id>/start-review", methods=["POST"])
@require_roles("ClaimsAdjuster")
def start_review(claim_id: str, _user_id: str, _role: str):
    cl = _get_claim(claim_id)
    get_json_body()
    if cl["status"] != "FILED":
        raise_err(ERR_CLAIM_INVALID_STATE, "Claim must be FILED to start review")
    policy = db.insurance_policies.get(cl["policy_id"])
    if policy is None or policy["status"] != "BOUND":
        raise_err(ERR_POLICY_INVALID_STATE, "Policy must be BOUND for review")
    cl["status"] = "UNDER_REVIEW"
    cl["reviewed_by_user_id"] = _user_id
    db.touch(cl)
    return success_object(pub(cl))


@bp.route("/freight/claims/<claim_id>/approve", methods=["POST"])
@require_roles("ClaimsAdjuster")
def approve_claim(claim_id: str, _user_id: str, _role: str):
    cl = _get_claim(claim_id)
    get_json_body()
    # Band 4: SoD — approver must differ from reviewer.
    if cl.get("reviewed_by_user_id") is not None and _user_id == cl["reviewed_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Claim approver must differ from the reviewer")
    if cl["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_INVALID_STATE, "Claim must be UNDER_REVIEW to approve")
    policy = db.insurance_policies.get(cl["policy_id"])
    cl["settlement_amount_cents"] = (
        domain.compute_settlement(cl, policy) if policy is not None else 0
    )
    cl["approved_by_user_id"] = _user_id
    cl["status"] = "APPROVED"
    db.touch(cl)
    return success_object(pub(cl))


@bp.route("/freight/claims/<claim_id>/deny", methods=["POST"])
@require_roles("ClaimsAdjuster")
def deny_claim(claim_id: str, _user_id: str, _role: str):
    cl = _get_claim(claim_id)
    get_json_body()
    # Band 4: SoD — denier must differ from reviewer.
    if cl.get("reviewed_by_user_id") is not None and _user_id == cl["reviewed_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Claim denier must differ from the reviewer")
    if cl["status"] != "UNDER_REVIEW":
        raise_err(ERR_CLAIM_INVALID_STATE, "Claim must be UNDER_REVIEW to deny")
    cl["settlement_amount_cents"] = 0
    cl["approved_by_user_id"] = _user_id
    cl["status"] = "DENIED"
    db.touch(cl)
    return success_object(pub(cl))


@bp.route("/freight/claims/<claim_id>/settle", methods=["POST"])
@require_roles("FinanceController")
def settle_claim(claim_id: str, _user_id: str, _role: str):
    cl = _get_claim(claim_id)
    get_json_body()
    if cl["status"] != "APPROVED":
        raise_err(ERR_CLAIM_INVALID_STATE, "Claim must be APPROVED to settle")
    cl["status"] = "SETTLED"
    cl["settled_at"] = db.now_domain_iso()
    db.touch(cl)
    return success_object(pub(cl))
