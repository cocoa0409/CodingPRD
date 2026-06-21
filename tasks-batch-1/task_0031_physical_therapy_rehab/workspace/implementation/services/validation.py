"""Reusable validation helpers used across route handlers.

These helpers raise ERR_INVALID_REQUEST (HTTP 400) on any malformed input —
the lowest-priority validation per PRD §2.11. Higher-priority validations
(auth/existence/state/business) live in route or service modules and are
checked before falling through to these.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Dict, Iterable, Optional

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND


# ---- primitive type/range checks --------------------------------------------


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Required field missing: {f}")


def require_string(value: Any, field_name: str, *, max_len: Optional[int] = None,
                   min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a string")
    if len(value) < min_len:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{field_name} must be at least {min_len} characters")
    if max_len is not None and len(value) > max_len:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{field_name} must be at most {max_len} characters")
    return value


def require_enum(value: Any, choices: Iterable[str], field_name: str) -> str:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"Invalid value for {field_name}: {value!r}",
        )
    return value


def require_int(
    value: Any,
    field_name: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    if min_value is not None and value < min_value:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be >= {min_value}"
        )
    if max_value is not None and value > max_value:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be <= {max_value}"
        )
    return value


def require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a boolean")
    return value


# ---- date / datetime helpers ------------------------------------------------


def require_date(value: Any, field_name: str) -> date:
    try:
        d = db.parse_iso_date(value)
    except (ValueError, TypeError):
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a YYYY-MM-DD date"
        )
    if d is None:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a YYYY-MM-DD date"
        )
    return d


def require_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be an ISO 8601 UTC timestamp",
        )
    try:
        dt = db.parse_iso_dt(value)
    except (ValueError, TypeError, AttributeError):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be an ISO 8601 UTC timestamp",
        )
    if dt is None:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be an ISO 8601 UTC timestamp",
        )
    return dt


def clock_today_utc() -> date:
    iso = db.get_current_utc()
    dt = db.parse_iso_dt(iso)
    assert dt is not None
    return dt.date()


# ---- FK / existence helpers -------------------------------------------------


def lookup_or_404(
    store: Dict[str, Dict[str, Any]], rid: Optional[str], kind: str
) -> Dict[str, Any]:
    """Raise ERR_RESOURCE_NOT_FOUND (404) when id is missing or absent.

    Used for both path-segment existence (PRD §2.5) and body-FK existence.
    """
    if not isinstance(rid, str) or not rid:
        raise APIError(ERR_RESOURCE_NOT_FOUND, 404, f"{kind} not found: {rid!r}")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_RESOURCE_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj


# ---- formatted-string constraints ------------------------------------------


_NPI_RE = re.compile(r"^\d{10}$")


def require_npi(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _NPI_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a 10-digit NPI"
        )
    return value


_STATE_RE = re.compile(r"^[A-Z]{2}$")


def require_state(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _STATE_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be a two-letter US state code",
        )
    return value


_FACILITY_RE = re.compile(r"^[A-Z0-9]{4,6}$")


def require_facility_code(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _FACILITY_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be uppercase 4-6 chars",
        )
    return value


_ICD10_RE = re.compile(r"^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$")


def require_icd10(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _ICD10_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be a valid ICD-10 diagnosis code",
        )
    return value
