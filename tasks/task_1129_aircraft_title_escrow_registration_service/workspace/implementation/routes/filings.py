"""Filing endpoints."""

from flask import Blueprint, request

import db
from db import (
    escrow_file_store, filing_store, aircraft_store, lien_store,
    make_common_fields, touch, now_iso, next_filing_sequence,
)
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_TRANSITION,
    ERR_FILE_ON_HOLD, ERR_ALREADY_TERMINAL, ERR_DUPLICATE_FILING,
    ERR_FILING_SEQUENCE_VIOLATION, ERR_LIENS_OUTSTANDING,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.escrow import try_bubble_recorded, try_bubble_verified
from validators import get_body, require_fields, require_string, require_enum

bp = Blueprint("filings", __name__)

VALID_FILING_TYPES = [
    "BILL_OF_SALE", "REGISTRATION_APPLICATION", "MORTGAGE_RECORDATION",
    "DEREGISTRATION", "EXPORT_CERTIFICATE",
]
FILING_ALLOWED_STATUSES = {"CLEARED", "FUNDED", "CLOSED", "RECORDED"}
SUBMIT_ALLOWED_STATUSES = {"CLOSED", "RECORDED"}
TERMINAL_STATUSES = {"CANCELLED", "VERIFIED"}

# Prerequisite chain: filing_type -> list of required ACCEPTED filing types
PREREQUISITES = {
    "REGISTRATION_APPLICATION": ["BILL_OF_SALE"],
    "MORTGAGE_RECORDATION": ["REGISTRATION_APPLICATION"],
    "DEREGISTRATION": ["BILL_OF_SALE"],
    "EXPORT_CERTIFICATE": ["DEREGISTRATION"],
}


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


def _get_filing_checked(id):
    f = filing_store.get(id)
    if not f:
        raise ApiError(ERR_NOT_FOUND, "Filing not found.", 404)
    return f


def _check_parent_mutable(filing):
    ef = escrow_file_store.get(filing["escrow_file_id"])
    if ef:
        if ef["status"] == "ON_HOLD":
            raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
        if ef["status"] in TERMINAL_STATUSES:
            raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    return ef


def _check_prerequisites(filing_type: str, escrow_file_id: str):
    """Check prerequisite filing types are ACCEPTED on the same file."""
    prereqs = PREREQUISITES.get(filing_type, [])
    for prereq_type in prereqs:
        found = any(
            f["escrow_file_id"] == escrow_file_id
            and f["filing_type"] == prereq_type
            and f["status"] == "ACCEPTED"
            for f in filing_store.values()
        )
        if not found:
            raise ApiError(
                ERR_FILING_SEQUENCE_VIOLATION,
                f"Prerequisite filing {prereq_type} is not ACCEPTED.",
                409,
            )


def _check_deregistration_gates(escrow_file_id: str):
    """DEREGISTRATION additionally requires all liens RELEASED and aircraft REGISTERED."""
    file_liens = [l for l in lien_store.values() if l["escrow_file_id"] == escrow_file_id]
    for ln in file_liens:
        if ln["status"] != "RELEASED":
            raise ApiError(ERR_LIENS_OUTSTANDING, "All liens must be RELEASED for DEREGISTRATION.", 409)

    ef = escrow_file_store.get(escrow_file_id)
    if ef:
        aircraft = aircraft_store.get(ef["aircraft_id"])
        if aircraft and aircraft["registry_status"] != "REGISTERED":
            raise ApiError(
                ERR_FILING_SEQUENCE_VIOLATION,
                "Aircraft registry_status must be REGISTERED for DEREGISTRATION.",
                409,
            )


@bp.route("/api/escrow-files/<id>/filings", methods=["POST"])
def create_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    ef = escrow_file_store.get(id)
    if not ef:
        raise ApiError(ERR_NOT_FOUND, "EscrowFile not found.", 404)

    if ef["status"] == "ON_HOLD":
        raise ApiError(ERR_FILE_ON_HOLD, "EscrowFile is ON_HOLD.", 409)
    if ef["status"] in TERMINAL_STATUSES:
        raise ApiError(ERR_ALREADY_TERMINAL, f"EscrowFile is {ef['status']}.", 409)
    if ef["status"] not in FILING_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot create filing in status {ef['status']}.", 409)

    body = get_body()
    require_fields(body, ["filing_type"])
    filing_type = require_enum(body["filing_type"], "filing_type", VALID_FILING_TYPES)

    # One non-WITHDRAWN filing per (escrow_file_id, filing_type)
    for f in filing_store.values():
        if f["escrow_file_id"] == id and f["filing_type"] == filing_type and f["status"] != "WITHDRAWN":
            raise ApiError(ERR_DUPLICATE_FILING, f"A non-WITHDRAWN {filing_type} filing already exists.", 409)

    fields = make_common_fields()
    filing = {
        **fields,
        "escrow_file_id": id,
        "aircraft_id": ef["aircraft_id"],
        "filing_type": filing_type,
        "status": "QUEUED",
        "verification_status": "NONE",
        "registry_confirmation_code": None,
        "reject_reason": None,
        "submitted_at": None,
        "sequence_index": None,
    }
    filing_store[filing["id"]] = filing
    return success_object(filing, 201)


@bp.route("/api/filings/<id>/submit", methods=["POST"])
def submit_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    filing = _get_filing_checked(id)
    ef = _check_parent_mutable(filing)

    if filing["status"] != "QUEUED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot submit filing in status {filing['status']}.", 409)

    if ef["status"] not in SUBMIT_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot submit filing when file is {ef['status']}.", 409)

    # Check prerequisites
    _check_prerequisites(filing["filing_type"], filing["escrow_file_id"])

    # DEREGISTRATION additional gates
    if filing["filing_type"] == "DEREGISTRATION":
        _check_deregistration_gates(filing["escrow_file_id"])

    filing["status"] = "SUBMITTED"
    filing["submitted_at"] = now_iso()
    filing["sequence_index"] = next_filing_sequence(filing["escrow_file_id"])
    touch(filing)

    # DEREGISTRATION side effect: Aircraft REGISTERED -> DEREGISTRATION_PENDING
    if filing["filing_type"] == "DEREGISTRATION":
        aircraft = aircraft_store.get(filing["aircraft_id"])
        if aircraft and aircraft["registry_status"] == "REGISTERED":
            aircraft["registry_status"] = "DEREGISTRATION_PENDING"
            touch(aircraft)

    return success_object(filing)


@bp.route("/api/filings/<id>/accept", methods=["POST"])
def accept_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    filing = _get_filing_checked(id)
    ef = _check_parent_mutable(filing)

    if filing["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot accept filing in status {filing['status']}.", 409)

    body = get_body()
    require_fields(body, ["confirmation_code"])
    confirmation_code = require_string(body["confirmation_code"], "confirmation_code")

    filing["status"] = "ACCEPTED"
    filing["registry_confirmation_code"] = confirmation_code
    filing["verification_status"] = "PENDING"
    touch(filing)

    # Aircraft side effects
    aircraft = aircraft_store.get(filing["aircraft_id"])
    if aircraft:
        if filing["filing_type"] == "DEREGISTRATION" and aircraft["registry_status"] == "DEREGISTRATION_PENDING":
            aircraft["registry_status"] = "DEREGISTERED"
            touch(aircraft)
        elif filing["filing_type"] == "EXPORT_CERTIFICATE" and aircraft["registry_status"] == "DEREGISTERED":
            aircraft["registry_status"] = "EXPORTED"
            touch(aircraft)

    # Bubble-up checks
    try_bubble_recorded(ef)
    try_bubble_verified(ef)

    return success_object(filing)


@bp.route("/api/filings/<id>/reject", methods=["POST"])
def reject_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    filing = _get_filing_checked(id)
    ef = _check_parent_mutable(filing)

    if filing["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot reject filing in status {filing['status']}.", 409)

    body = get_body()
    require_fields(body, ["reason"])
    reason = require_string(body["reason"], "reason")

    filing["status"] = "REJECTED"
    filing["reject_reason"] = reason
    touch(filing)
    return success_object(filing)


@bp.route("/api/filings/<id>/resubmit", methods=["POST"])
def resubmit_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    filing = _get_filing_checked(id)
    ef = _check_parent_mutable(filing)

    if filing["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot resubmit filing in status {filing['status']}.", 409)

    if ef["status"] not in SUBMIT_ALLOWED_STATUSES:
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot resubmit filing when file is {ef['status']}.", 409)

    # Re-evaluate prerequisites
    _check_prerequisites(filing["filing_type"], filing["escrow_file_id"])

    # DEREGISTRATION additional gates
    if filing["filing_type"] == "DEREGISTRATION":
        _check_deregistration_gates(filing["escrow_file_id"])

    filing["status"] = "SUBMITTED"
    filing["submitted_at"] = now_iso()
    filing["sequence_index"] = next_filing_sequence(filing["escrow_file_id"])
    filing["reject_reason"] = None
    touch(filing)

    return success_object(filing)


@bp.route("/api/filings/<id>/verify", methods=["POST"])
def verify_filing(id):
    user_id, role = require_roles(["EscrowOfficer"])
    filing = _get_filing_checked(id)
    ef = _check_parent_mutable(filing)

    if filing["verification_status"] not in ("PENDING", "MISMATCHED"):
        raise ApiError(ERR_INVALID_TRANSITION, f"Cannot verify filing with verification_status {filing['verification_status']}.", 409)

    body = get_body()
    require_fields(body, ["recorded_confirmation_code"])
    recorded_code = require_string(body["recorded_confirmation_code"], "recorded_confirmation_code")

    if recorded_code == filing["registry_confirmation_code"]:
        filing["verification_status"] = "MATCHED"
    else:
        filing["verification_status"] = "MISMATCHED"
    touch(filing)

    # VERIFIED bubble-up check
    try_bubble_verified(ef)

    return success_object(filing)


@bp.route("/api/filings", methods=["GET"])
def list_filings():
    user_id, role = require_roles(ALL_ROLES)
    items = list(filing_store.values())

    escrow_file_id = request.args.get("escrow_file_id")
    aircraft_id = request.args.get("aircraft_id")
    filing_type = request.args.get("filing_type")
    status = request.args.get("status")

    if escrow_file_id:
        items = [f for f in items if f["escrow_file_id"] == escrow_file_id]
    if aircraft_id:
        items = [f for f in items if f["aircraft_id"] == aircraft_id]
    if filing_type:
        items = [f for f in items if f["filing_type"] == filing_type]
    if status:
        items = [f for f in items if f["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    limit = _parse_limit()
    offset = _parse_offset()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list(items, limit, offset, total)


@bp.route("/api/filings/<id>", methods=["GET"])
def get_filing(id):
    user_id, role = require_roles(ALL_ROLES)
    filing = _get_filing_checked(id)
    return success_object(filing)
