"""Borrower routes."""
from __future__ import annotations

from flask import Blueprint, g

import db
import response
from errors import ApiError, ERR_UNAUTHORIZED
from middleware import require_auth
from services.common import (
    bump,
    new_common_fields,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import get_borrower, get_or_404

bp = Blueprint("borrowers", __name__)


def _serialize(b: dict) -> dict:
    return strip_internal(b)


def _check_borrower_self(borrower_id: str):
    """Borrower role may only read own row."""
    if g.user_role == "Borrower" and g.user_id != borrower_id:
        raise ApiError(ERR_UNAUTHORIZED, "Borrower may only access their own record.")


@bp.post("/borrowers")
@require_auth(roles=["LoanServicer", "ComplianceOfficer"])
def create_borrower():
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    ssn_last4 = require_str(body, "ssn_last4")

    with db.lock:
        # Uniqueness on email
        for existing in db.borrowers.values():
            if existing.get("email") == email:
                # Not in the formal error catalog; fold into ERR_INVALID_REQUEST per priority 15
                from errors import ERR_INVALID_REQUEST
                raise ApiError(ERR_INVALID_REQUEST, "Email already exists.")
        b = new_common_fields()
        b["email"] = email
        b["full_name"] = full_name
        b["ssn_last4"] = ssn_last4
        db.borrowers[b["id"]] = b
    return response.ok(_serialize(b), status=201)


@bp.get("/borrowers/<borrower_id>")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def read_borrower(borrower_id: str):
    _check_borrower_self(borrower_id)
    b = get_borrower(borrower_id)
    return response.ok(_serialize(b))


@bp.get("/borrowers/<borrower_id>/loans")
@require_auth(roles=["LoanServicer", "ComplianceOfficer", "Borrower"])
def list_borrower_loans(borrower_id: str):
    # Path existence check first
    get_borrower(borrower_id)
    _check_borrower_self(borrower_id)

    limit, offset = parse_pagination()
    items = [l for l in db.loans.values() if l.get("borrower_id") == borrower_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([strip_internal(x) for x in page], limit, offset, total)
