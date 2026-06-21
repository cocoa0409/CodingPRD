"""Applicant routes."""
from __future__ import annotations

import re
from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST, ERR_APPLICANT_NOT_FOUND
from middleware import require_auth
from services.common import (
    bump,
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    require_int_range,
    require_str,
    sorted_by_created_at,
)
from services.lookup import get_applicant_or_404

bp = Blueprint("applicants", __name__)


# USPS state codes (50 states + DC + a few territories commonly used).
_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY", "PR", "VI", "GU", "AS", "MP",
}


def _validate_state_code(v: str, field: str) -> str:
    if not isinstance(v, str) or len(v) != 2 or not v.isalpha() or v.upper() != v:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a two-letter uppercase USPS state code.")
    if v not in _STATE_CODES:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is not a recognized USPS state code.")
    return v


def _validate_email(v: str) -> str:
    # Simple sanity check; we treat the value purely as opaque key.
    if not isinstance(v, str) or "@" not in v or "." not in v.split("@")[-1]:
        raise ApiError(ERR_INVALID_REQUEST, "email must look like a valid email address.")
    return v


def _validate_ssn_last4(v: str) -> str:
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}", v):
        raise ApiError(ERR_INVALID_REQUEST, "ssn_last4 must be exactly four digits.")
    return v


def _applicant_to_dict(a: dict) -> dict:
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "email": a["email"],
        "ssn_last4": a["ssn_last4"],
        "annual_income_cents": a["annual_income_cents"],
        "monthly_debt_cents": a["monthly_debt_cents"],
        "credit_score": a["credit_score"],
        "state_code": a["state_code"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.post("/applicants")
@require_auth(roles=["LoanOfficer"])
def create_applicant():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = _validate_email(require_str(body, "email"))
    ssn_last4 = _validate_ssn_last4(require_str(body, "ssn_last4"))
    annual_income_cents = require_int(body, "annual_income_cents")
    monthly_debt_cents = require_int(body, "monthly_debt_cents")
    credit_score = require_int_range(body, "credit_score", low=300, high=850)
    state_code = _validate_state_code(require_str(body, "state_code"), "state_code")

    if annual_income_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "annual_income_cents must be non-negative.")
    if monthly_debt_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, "monthly_debt_cents must be non-negative.")

    # Uniqueness on email across all applicants.
    for a in db.applicants.values():
        if a["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, "email already in use.")

    with db.lock:
        applicant = {
            **new_common_fields(),
            "full_name": full_name,
            "email": email,
            "ssn_last4": ssn_last4,
            "annual_income_cents": annual_income_cents,
            "monthly_debt_cents": monthly_debt_cents,
            "credit_score": credit_score,
            "state_code": state_code,
        }
        db.applicants[applicant["id"]] = applicant
    return response.ok(_applicant_to_dict(applicant), status=201)


@bp.get("/applicants/<aid>")
@require_auth(roles=["LoanOfficer", "Underwriter", "ComplianceOfficer"])
def get_applicant(aid: str):
    a = db.applicants.get(aid)
    if a is None:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "Applicant not found.")
    return response.ok(_applicant_to_dict(a))


@bp.get("/applicants")
@require_auth(roles=["LoanOfficer", "Underwriter", "ComplianceOfficer"])
def list_applicants():
    limit, offset = parse_pagination()
    email = request.args.get("email")
    state_code = request.args.get("state_code")

    items = list(db.applicants.values())
    if email is not None:
        items = [a for a in items if a["email"] == email]
    if state_code is not None:
        items = [a for a in items if a["state_code"] == state_code]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([_applicant_to_dict(a) for a in page], limit, offset, total)
