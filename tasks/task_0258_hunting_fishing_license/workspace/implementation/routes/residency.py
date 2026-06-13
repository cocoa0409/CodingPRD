"""ResidencyVerification endpoints (PRD §3.1)."""
from flask import Blueprint, request

import serialize
from db import store
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import success, success_list
from validation import (
    get_json_body, as_nonempty_str, as_enum, as_int, parse_pagination, paginate,
)
from services.core import (
    get_applicant_or_404, get_residency_verification_or_404, RESIDENCY_MIN_MONTHS,
)

bp = Blueprint("residency", __name__)

PROOF_TYPES = {"DRIVERS_LICENSE", "UTILITY_BILL", "TAX_RECORD", "TRIBAL_ID"}


@bp.route("/residency-verifications", methods=["POST"])
@require_roles("Applicant", "DrawOfficer")
def create_residency_verification():
    body = get_json_body()
    applicant_id = as_nonempty_str(body, "applicant_id", required=True)
    proof_type = as_enum(body, "proof_type", PROOF_TYPES, required=True)
    proof_state_code = as_nonempty_str(body, "proof_state_code", required=True)
    continuous_months = as_int(body, "continuous_months", required=True, minimum=0)

    # Existence (FK) — checked before any business rule (PRD §2.5).
    get_applicant_or_404(applicant_id)

    record = {
        "applicant_id": applicant_id,
        "proof_type": proof_type,
        "proof_state_code": proof_state_code,
        "continuous_months": continuous_months,
        "status": "PENDING",
        "resulting_residency": None,
    }
    store.stamp_new(record)
    store.residency_verifications[record["id"]] = record
    return success(
        serialize.residency_verification(record), status=201, response_type="object"
    )


@bp.route("/residency-verifications/<id>", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def get_residency_verification(id):
    record = get_residency_verification_or_404(id)
    return success(
        serialize.residency_verification(record), status=200, response_type="object"
    )


@bp.route("/residency-verifications", methods=["GET"])
@require_roles("DrawOfficer", "Applicant")
def list_residency_verifications():
    limit, offset = parse_pagination()
    items = list(store.residency_verifications.values())
    applicant_id = request.args.get("applicant_id")
    if applicant_id is not None:
        items = [r for r in items if r["applicant_id"] == applicant_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list(
        [serialize.residency_verification(r) for r in page], limit, offset, total
    )


@bp.route("/residency-verifications/<id>/approve", methods=["POST"])
@require_roles("DrawOfficer")
def approve_residency_verification(id):
    record = get_residency_verification_or_404(id)
    if record["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Verification is not PENDING")
    applicant = get_applicant_or_404(record["applicant_id"])
    # resulting_residency = RESIDENT when proof state matches declared and
    # months >= threshold, else NONRESIDENT (PRD §3.1).
    if (
        record["proof_state_code"] == applicant["declared_state_code"]
        and record["continuous_months"] >= RESIDENCY_MIN_MONTHS
    ):
        resulting = "RESIDENT"
    else:
        resulting = "NONRESIDENT"
    record["status"] = "APPROVED"
    record["resulting_residency"] = resulting
    store.touch(record)
    # Cross-entity write onto the applicant + version bump (PRD §2.4, §3.1).
    applicant["residency_status"] = resulting
    store.touch(applicant)
    return success(
        serialize.residency_verification(record), status=200, response_type="object"
    )


@bp.route("/residency-verifications/<id>/deny", methods=["POST"])
@require_roles("DrawOfficer")
def deny_residency_verification(id):
    record = get_residency_verification_or_404(id)
    if record["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Verification is not PENDING")
    record["status"] = "DENIED"
    store.touch(record)
    # Applicant.residency_status left unchanged (PRD §3.1).
    return success(
        serialize.residency_verification(record), status=200, response_type="object"
    )
