"""DisbursementInstruction endpoints."""

from flask import Blueprint, request

import db
from db import (
    escrow_file_store, disbursement_store, lien_store, party_store,
    make_common_fields, touch,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_STALE_VERSION,
    ERR_SEGREGATION_OF_DUTIES, ERR_LIEN_NOT_RELEASED, ERR_ESCROW_SHORTFALL,
    ERR_PAYOFF_MISMATCH,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import recompute_totals
from validators import get_body, require_fields, require_string, require_positive_int, require_enum

bp = Blueprint("disbursements", __name__)

VALID_PURPOSES = ["LIEN_PAYOFF", "SELLER_PROCEEDS", "ESCROW_FEE", "TAX_REMITTANCE", "OTHER"]
DRAFT_ALLOWED_STATUSES = {"SEARCH_COMPLETE", "CLEARED", "FUNDED", "CLOSED", "RECORDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}
RELEASE_ALLOWED_STATUSES = {"CLOSED", "RECORDED"}


def _parse_limit():
    try:
        v = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        v = 10
    return max(1, min(100, v))


def _parse_offset():
    try:
        v = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        v = 0
    return max(0, v)


@bp.route("/api/escrow-files/<id>/disbursements", methods=["POST"])
def create_disbursement(id):
    user_id, role = require_roles(["EscrowOfficer", "EscrowManager"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    if ef["status"] not in DRAFT_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot create disbursement in status {ef['status']}.", 409)

    body = get_body()
    require_fields(
        body,
        ["payee_party_id", "amount_cents", "purpose", "expected_escrow_file_version"],
        ["lien_id"],
    )

    payee_party_id = require_string(body["payee_party_id"], "payee_party_id")
    amount_cents = require_positive_int(body["amount_cents"], "amount_cents")
    purpose = require_enum(body["purpose"], "purpose", VALID_PURPOSES)
    lien_id = body.get("lien_id")
    expected_version = body["expected_escrow_file_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise ApiError(ERR_INVALID_REQUEST, "expected_escrow_file_version must be an integer.", 400)

    # LIEN_PAYOFF requires lien_id
    if purpose == "LIEN_PAYOFF":
        if not lien_id:
            raise ApiError(ERR_INVALID_REQUEST, "lien_id is required for LIEN_PAYOFF.", 400)
        # Verify lien belongs to this file
        lien = lien_store.get(lien_id)
        if not lien:
            raise ApiError(ERR_NOT_FOUND, "Lien not found.", 404)
        if lien["escrow_file_id"] != id:
            raise ApiError(ERR_NOT_FOUND, "Lien does not belong to this escrow file.", 404)
    else:
        if lien_id is not None:
            raise ApiError(ERR_INVALID_REQUEST, "lien_id must be omitted for non-LIEN_PAYOFF purposes.", 400)

    # Existence: payee party
    if not party_store.get(payee_party_id):
        raise ApiError(ERR_NOT_FOUND, "Payee party not found.", 404)

    # OCC check
    if expected_version != ef["version"]:
        raise ApiError(ERR_STALE_VERSION, "EscrowFile version mismatch.", 412)

    fields = make_common_fields()
    disb = {
        **fields,
        "escrow_file_id": id,
        "payee_party_id": payee_party_id,
        "lien_id": lien_id if purpose == "LIEN_PAYOFF" else None,
        "amount_cents": amount_cents,
        "purpose": purpose,
        "status": "PENDING_APPROVAL",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
    }
    disbursement_store[disb["id"]] = disb

    # Increment file version
    touch(ef)

    return success_object(disb, 201)


@bp.route("/api/disbursements/<id>/approve", methods=["POST"])
def approve_disbursement(id):
    user_id, role = require_roles(["EscrowManager"])
    disb = disbursement_store.get(id)
    if not disb:
        raise ApiError(ERR_NOT_FOUND, "DisbursementInstruction not found.", 404)

    # Check parent file
    ef = escrow_file_store.get(disb["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if disb["status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot approve disbursement in status {disb['status']}.", 409)

    # Segregation of duties
    if user_id == disb["created_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Approver cannot be the same as drafter.", 403)

    disb["approved_by_user_id"] = user_id
    disb["status"] = "APPROVED"
    touch(disb)
    return success_object(disb)


@bp.route("/api/disbursements/<id>/release", methods=["POST"])
def release_disbursement(id):
    user_id, role = require_roles(["EscrowManager"])
    disb = disbursement_store.get(id)
    if not disb:
        raise ApiError(ERR_NOT_FOUND, "DisbursementInstruction not found.", 404)

    ef = escrow_file_store.get(disb["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if disb["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot release disbursement in status {disb['status']}.", 409)

    # File must be in CLOSED or RECORDED
    if not ef or ef["status"] not in RELEASE_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, "EscrowFile must be CLOSED or RECORDED for release.", 409)

    # Shortfall check (amount <= escrow_balance)
    recompute_totals(ef)
    if disb["amount_cents"] > ef["escrow_balance_cents"]:
        raise ApiError(ERR_ESCROW_SHORTFALL, "Amount exceeds escrow balance.", 422)

    # LIEN_PAYOFF checks
    if disb["purpose"] == "LIEN_PAYOFF":
        lien = lien_store.get(disb["lien_id"])
        if not lien:
            raise ApiError(ERR_NOT_FOUND, "Lien not found.", 404)
        if lien["status"] != "RELEASED":
            raise ApiError(ERR_LIEN_NOT_RELEASED, "Lien is not RELEASED.", 409)
        if disb["amount_cents"] != lien["amount_paid_cents"]:
            raise ApiError(ERR_PAYOFF_MISMATCH, "Amount does not match lien amount_paid_cents.", 422)

    disb["status"] = "RELEASED"
    touch(disb)

    # Recompute totals on file
    recompute_totals(ef)
    touch(ef)

    return success_object(disb)


@bp.route("/api/disbursements/<id>/void", methods=["POST"])
def void_disbursement(id):
    user_id, role = require_roles(["EscrowManager"])
    disb = disbursement_store.get(id)
    if not disb:
        raise ApiError(ERR_NOT_FOUND, "DisbursementInstruction not found.", 404)

    ef = escrow_file_store.get(disb["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if disb["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot void disbursement in status {disb['status']}.", 409)

    disb["status"] = "VOIDED"
    touch(disb)
    return success_object(disb)


@bp.route("/api/disbursements", methods=["GET"])
def list_disbursements():
    user_id, role = require_roles(ALL_ROLES)
    items = list(disbursement_store.values())

    escrow_file_id = request.args.get("escrow_file_id")
    payee_party_id = request.args.get("payee_party_id")
    lien_id = request.args.get("lien_id")
    status = request.args.get("status")

    if escrow_file_id:
        items = [d for d in items if d["escrow_file_id"] == escrow_file_id]
    if payee_party_id:
        items = [d for d in items if d["payee_party_id"] == payee_party_id]
    if lien_id:
        items = [d for d in items if d.get("lien_id") == lien_id]
    if status:
        items = [d for d in items if d["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/disbursements/<id>", methods=["GET"])
def get_disbursement(id):
    user_id, role = require_roles(ALL_ROLES)
    disb = disbursement_store.get(id)
    if not disb:
        raise ApiError(ERR_NOT_FOUND, "DisbursementInstruction not found.", 404)
    return success_object(disb)
