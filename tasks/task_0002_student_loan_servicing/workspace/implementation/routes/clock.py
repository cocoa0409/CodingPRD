"""Test-driving clock endpoints."""
from __future__ import annotations

import re
from datetime import datetime

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_CLOCK, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from routes._common import get_field, parse_json_body
from services import loan_ops

bp = Blueprint("clock", __name__)


def _normalize_to_date(s: str) -> str:
    """Accept either a YYYY-MM-DD date or a full ISO 8601 datetime; return YYYY-MM-DD."""
    if not isinstance(s, str):
        raise APIError(ERR_INVALID_REQUEST, "to_iso8601 must be string")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    # Try full ISO 8601 datetime
    try:
        # Python's fromisoformat doesn't handle 'Z' suffix prior to 3.11; strip it
        normalized = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")


@bp.post("/v1/_clock/advance")
@require_roles({"LoanServicer"})
def advance_clock():
    body = parse_json_body()
    target = get_field(body, "to_iso8601")
    target_date = _normalize_to_date(target)
    current = db.get_clock_date()
    if target_date <= current:
        raise APIError(ERR_INVALID_CLOCK, "to_iso8601 must be strictly greater than current clock")
    loan_ops.advance_clock(target_date)
    return success({"clock_date": db.get_clock_date()}, status=200)


@bp.get("/v1/_clock")
@require_roles({"LoanServicer", "PSLFAdjudicator", "VADischargeOfficer", "Borrower"})
def read_clock():
    return success({"clock_date": db.get_clock_date()}, status=200)
