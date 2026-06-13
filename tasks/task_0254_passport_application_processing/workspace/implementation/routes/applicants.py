"""Applicant registration and reads."""
from __future__ import annotations

from datetime import date

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
)
from services.calculations import parse_iso_to_date

bp = Blueprint("applicants", __name__)


def _valid_past_date(dob: str) -> date:
    try:
        d = date.fromisoformat(dob)
    except (ValueError, TypeError):
        raise APIError(ERR_INVALID_REQUEST, 400, "date_of_birth must be YYYY-MM-DD")
    today = parse_iso_to_date(db.clock.now_iso())
    if d >= today:
        raise APIError(ERR_INVALID_REQUEST, 400, "date_of_birth must be a valid past date")
    return d


def _compute_is_minor(dob: date) -> bool:
    """True when the applicant has NOT yet reached their 16th birthday."""
    today = parse_iso_to_date(db.clock.now_iso())
    sixteenth = _add_years(dob, 16)
    return today < sixteenth


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on a non-leap target year
        return d.replace(year=d.year + years, day=28)


def _apply_is_minor(applicant: dict) -> None:
    dob = date.fromisoformat(applicant["date_of_birth"])
    applicant["is_minor"] = _compute_is_minor(dob)


@bp.route("/applicants", methods=["POST"])
def create_applicant():
    # Anonymous endpoint per PRD §2.1 — no auth headers required.
    body = get_body()
    if "full_legal_name" not in body or body.get("full_legal_name") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: full_legal_name")
    if "date_of_birth" not in body or body.get("date_of_birth") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: date_of_birth")
    if "email" not in body or body.get("email") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: email")

    name = require_str(body, "full_legal_name", max_len=120)
    dob_str = require_str(body, "date_of_birth")
    dob = _valid_past_date(dob_str)
    email_raw = require_str(body, "email")
    email = email_raw.lower()

    # Unique email across applicants
    for a in db.applicants.values():
        if a["email"] == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already registered")

    guardian_id = body.get("guardian_applicant_id")
    if guardian_id is not None:
        if not isinstance(guardian_id, str):
            raise APIError(ERR_INVALID_REQUEST, 400, "guardian_applicant_id must be a string")
        if guardian_id not in db.applicants:
            from errors import ERR_FK_NOT_FOUND
            raise APIError(ERR_FK_NOT_FOUND, 422, "guardian_applicant_id does not exist")

    applicant = {
        "full_legal_name": name,
        "date_of_birth": dob.isoformat(),
        "email": email,
        "guardian_applicant_id": guardian_id,
        "is_minor": False,  # computed below
        "verification_risk_score": 0,
        "total_fees_paid_cents": 0,
    }
    stamp_create(applicant, full=True)
    _apply_is_minor(applicant)
    db.applicants[applicant["id"]] = applicant
    return ok_object(serialize(applicant), 201)


@bp.route("/applicants/<rid>", methods=["GET"])
def get_applicant(rid):
    require_auth(["Applicant", "Adjudicator", "AcceptanceAgent"])
    rec = db.applicants.get(rid)
    if rec is None:
        from errors import ERR_NOT_FOUND
        raise APIError(ERR_NOT_FOUND, 404, "Applicant not found")
    # is_minor recomputed when referenced
    _apply_is_minor(rec)
    return ok_object(serialize(rec), 200)


@bp.route("/applicants", methods=["GET"])
def list_applicants():
    require_auth(["Adjudicator", "AcceptanceAgent"])
    limit, offset = parse_pagination()
    from flask import request

    items = list(db.applicants.values())
    guardian = request.args.get("guardian_applicant_id")
    if guardian is not None:
        items = [a for a in items if a.get("guardian_applicant_id") == guardian]
    items = order_by_created(items)
    for a in items:
        _apply_is_minor(a)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
