"""Reusable validation helpers used across route handlers.

The priority ladder is enforced by the call order inside each route handler;
this module supplies the leaf checks.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Iterable, List
from datetime import date, datetime, timedelta, timezone

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCED_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
)


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    """Raise ERR_INVALID_REQUEST if any required field is missing/None.

    Empty string and empty list are also considered missing because the
    scaffold uniformly treats them as 'absent input' for required slots.
    """
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Required field missing: {f}")


def require_enum(value: Any, choices: Iterable[str], field_name: str) -> None:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"Invalid value for {field_name}: {value}",
        )


def require_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a non-empty string")


def require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    return value


def lookup_or_404(store: Dict[str, Dict[str, Any]], rid: str, kind: str) -> Dict[str, Any]:
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


def lookup_fk_or_referenced(
    store: Dict[str, Dict[str, Any]], rid: str, kind: str
) -> Dict[str, Any]:
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_REFERENCED_NOT_FOUND, 404, f"Referenced {kind} not found: {rid}")
    return obj


def ensure_case_ownership(case: Dict[str, Any], role: str, user_id: str) -> None:
    """For Applicant/Attorney roles, enforce ownership of the case.

    Officer / FieldOfficeAdmin bypass — they don't 'own' cases.
    """
    if role == "Applicant":
        if case.get("applicant_id") != user_id:
            raise APIError(ERR_OWNERSHIP_VIOLATION, 403, "Applicant does not own this case")
    elif role == "Attorney":
        if case.get("attorney_id") != user_id:
            raise APIError(ERR_OWNERSHIP_VIOLATION, 403, "Attorney does not represent this case")
    # Officer / FieldOfficeAdmin: no ownership constraint at this layer.


# Time/date helpers for appointment / clock validations -----------------------

def parse_clock_dt() -> datetime:
    return db.parse_iso_dt(db.get_current_utc())  # type: ignore[return-value]


def parse_appt_dt(value: Any, field_name: str) -> datetime:
    try:
        dt = db.parse_iso_dt(value)
    except (ValueError, TypeError, AttributeError):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an ISO 8601 timestamp")
    return dt


def evaluation_month_from_clock() -> str:
    """YYYY-MM portion of the logical clock (scaffold §1.3.visa_availability)."""
    return db.get_current_utc()[:7]
