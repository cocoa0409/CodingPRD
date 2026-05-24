"""Borrower endpoints."""
from __future__ import annotations

import re

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_EMAIL_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import success, success_list
from routes._common import (
    borrower_ownership_check,
    get_field,
    must_get,
    paginate_sorted,
    parse_json_body,
    parse_pagination,
)
from services import serializer

bp = Blueprint("borrowers", __name__)

VALID_MIL = {"NONE", "ACTIVE_DUTY", "VETERAN", "DISABLED_VETERAN"}


@bp.post("/v1/borrowers")
def create_borrower():
    """LoanServicer only — but POST /v1/borrowers is the public endpoint exception.

    Per scaffold §1.4 priority 1 applies_to: "all except [POST /borrowers]".
    Per scaffold §1.7 the operation is in LoanServicer.exclusive_operations.
    Since the endpoint is publicly callable (no auth headers required), we accept
    any caller. The auth middleware skips for this route.
    """
    body = parse_json_body()
    ssn_last4 = get_field(body, "ssn_last4")
    full_name = get_field(body, "full_name")
    date_of_birth = get_field(body, "date_of_birth")
    email = get_field(body, "email")
    military_status = body.get("military_status", "NONE")

    # Validate fields
    if not isinstance(ssn_last4, str) or not re.fullmatch(r"\d{4}", ssn_last4):
        raise APIError(ERR_INVALID_REQUEST, "ssn_last4 must be exactly 4 digits")
    if not isinstance(full_name, str) or not full_name.strip():
        raise APIError(ERR_INVALID_REQUEST, "full_name required")
    if not isinstance(date_of_birth, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_of_birth):
        raise APIError(ERR_INVALID_REQUEST, "date_of_birth must be YYYY-MM-DD")
    if not isinstance(email, str) or "@" not in email:
        raise APIError(ERR_INVALID_REQUEST, "email required")
    if military_status not in VALID_MIL:
        raise APIError(ERR_INVALID_REQUEST, "military_status invalid")

    # Priority 31: email unique case-insensitive
    email_lc = email.lower()
    for existing in db.borrowers.values():
        if existing["email"].lower() == email_lc:
            raise APIError(ERR_EMAIL_DUPLICATE, "Email already exists")

    bid = db.new_id()
    now = db.now_iso()
    borrower = {
        "id": bid,
        "ssn_last4": ssn_last4,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "email": email,
        "military_status": military_status,
        "aggregate_outstanding_principal_cents": 0,
        "borrower_status": "CURRENT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.borrowers[bid] = borrower
    return success(serializer.serialize_borrower(borrower), status=201)


@bp.get("/v1/borrowers/<borrower_id>")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer", "Borrower"})
def get_borrower(borrower_id):
    b = must_get(db.borrowers, borrower_id, "Borrower")
    borrower_ownership_check(borrower_id)
    return success(serializer.serialize_borrower(b), status=200)


@bp.get("/v1/borrowers")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer"})
def list_borrowers():
    limit, offset = parse_pagination()
    items = sorted(db.borrowers.values(), key=lambda b: b["created_at"])
    page, total = paginate_sorted(items, limit, offset)
    return success_list(
        [serializer.serialize_borrower(b) for b in page], limit, offset, total
    )


@bp.patch("/v1/borrowers/<borrower_id>/military-status")
@require_roles({"LoanServicer"})
def update_military_status(borrower_id):
    b = must_get(db.borrowers, borrower_id, "Borrower")
    body = parse_json_body()
    military_status = get_field(body, "military_status")
    if military_status not in VALID_MIL:
        raise APIError(ERR_INVALID_REQUEST, "military_status invalid")
    b["military_status"] = military_status
    b["updated_at"] = db.now_iso()
    b["version"] = b.get("version", 0) + 1
    return success(serializer.serialize_borrower(b), status=200)
