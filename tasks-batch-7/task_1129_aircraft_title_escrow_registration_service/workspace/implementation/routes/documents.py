"""ClosingDocument endpoints."""

from flask import Blueprint, request

from db import (
    escrow_file_store, closing_document_store, party_store, make_common_fields, touch,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_SIGNER_NOT_PARTY,
    ERR_SIGNER_NOT_REQUIRED, ERR_ALREADY_SIGNED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from validators import get_body, require_fields, require_string, require_enum

bp = Blueprint("documents", __name__)

VALID_DOC_TYPES = [
    "PURCHASE_AGREEMENT", "ESCROW_INSTRUCTIONS", "BILL_OF_SALE_DOC",
    "WIRE_AUTHORIZATION", "CLOSING_STATEMENT",
]
DOC_ALLOWED_STATUSES = {"SEARCH_COMPLETE", "CLEARED", "FUNDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}


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


def _get_file_parties(ef: dict) -> set:
    """Get the set of party IDs on this file."""
    parties = {ef["buyer_party_id"], ef["seller_party_id"]}
    if ef.get("lender_party_id"):
        parties.add(ef["lender_party_id"])
    if ef.get("trustee_party_id"):
        parties.add(ef["trustee_party_id"])
    return parties


@bp.route("/api/escrow-files/<id>/documents", methods=["POST"])
def create_document(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    if ef["status"] not in DOC_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot create document in status {ef['status']}.", 409)

    body = get_body()
    require_fields(body, ["doc_type", "required_signer_party_ids"])
    doc_type = require_enum(body["doc_type"], "doc_type", VALID_DOC_TYPES)
    signers = body["required_signer_party_ids"]
    if not isinstance(signers, list):
        raise ApiError(ERR_INVALID_REQUEST, "required_signer_party_ids must be an array.", 400)

    # Validate every signer is a party on the file
    file_parties = _get_file_parties(ef)
    for signer_id in signers:
        if not isinstance(signer_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "Each signer must be a string party id.", 400)
        if signer_id not in file_parties:
            raise ApiError(ERR_SIGNER_NOT_PARTY, f"Signer {signer_id} is not a party on this file.", 422)

    fields = make_common_fields()
    doc = {
        **fields,
        "escrow_file_id": id,
        "doc_type": doc_type,
        "required_signer_party_ids": signers,
        "signed_party_ids": [],
        "status": "PREPARED",
    }
    closing_document_store[doc["id"]] = doc

    # Increment file version
    touch(ef)

    return success_object(doc, 201)


@bp.route("/api/documents/<id>/send", methods=["POST"])
def send_document(id):
    user_id, role = require_roles(["EscrowOfficer"])
    doc = closing_document_store.get(id)
    if not doc:
        raise ApiError(ERR_NOT_FOUND, "ClosingDocument not found.", 404)

    ef = escrow_file_store.get(doc["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if doc["status"] != "PREPARED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot send document in status {doc['status']}.", 409)

    doc["status"] = "OUT_FOR_SIGNATURE"
    touch(doc)
    return success_object(doc)


@bp.route("/api/documents/<id>/sign", methods=["POST"])
def sign_document(id):
    user_id, role = require_roles(["EscrowOfficer"])
    doc = closing_document_store.get(id)
    if not doc:
        raise ApiError(ERR_NOT_FOUND, "ClosingDocument not found.", 404)

    ef = escrow_file_store.get(doc["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)

    if doc["status"] not in ("OUT_FOR_SIGNATURE", "PARTIALLY_SIGNED"):
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot sign document in status {doc['status']}.", 409)

    body = get_body()
    require_fields(body, ["signer_party_id"])
    signer_id = require_string(body["signer_party_id"], "signer_party_id")

    # Priority 19: Must not already be signed
    if signer_id in doc["signed_party_ids"]:
        raise ApiError(ERR_ALREADY_SIGNED, "Signer has already signed.", 409)

    # Priority 21: Must be in required_signer_party_ids
    if signer_id not in doc["required_signer_party_ids"]:
        raise ApiError(ERR_SIGNER_NOT_REQUIRED, "Signer is not in required_signer_party_ids.", 422)

    doc["signed_party_ids"].append(signer_id)

    # Check if fully signed
    if set(doc["signed_party_ids"]) == set(doc["required_signer_party_ids"]):
        doc["status"] = "FULLY_SIGNED"
    else:
        doc["status"] = "PARTIALLY_SIGNED"

    touch(doc)
    return success_object(doc)


@bp.route("/api/escrow-files/<id>/documents", methods=["GET"])
def list_documents(id):
    user_id, role = require_roles(ALL_ROLES)
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    items = [d for d in closing_document_store.values() if d["escrow_file_id"] == id]
    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)
