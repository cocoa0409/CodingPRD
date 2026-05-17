"""Generic request-parsing and validation helpers.

These keep route handlers focused on business logic by centralizing the
"is this field present and of the right type" boilerplate. All shape failures
raise ERR_VALIDATION (priority 120).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import request

from .clock import parse_iso, parse_iso_date
from .errors import APIError


# -----------------------------------------------------------------------------
# Body parsing
# -----------------------------------------------------------------------------
def parse_json_body(required: bool = True) -> dict:
    """Return the JSON body as a dict, raising ERR_VALIDATION on bad shape."""
    if request.content_length in (None, 0):
        if required:
            return {}
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception as exc:  # noqa: BLE001
        raise APIError("ERR_VALIDATION", f"Malformed JSON body: {exc}") from exc
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_field(body: dict, key: str, type_check=None):
    if key not in body:
        raise APIError("ERR_VALIDATION", f"Missing required field '{key}'.")
    val = body[key]
    if val is None:
        raise APIError("ERR_VALIDATION", f"Field '{key}' must not be null.")
    if type_check is not None and not type_check(val):
        raise APIError("ERR_VALIDATION", f"Field '{key}' has invalid type.")
    return val


def optional_field(body: dict, key: str, default=None, type_check=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if type_check is not None and not type_check(val):
        raise APIError("ERR_VALIDATION", f"Field '{key}' has invalid type.")
    return val


# -----------------------------------------------------------------------------
# Type predicates
# -----------------------------------------------------------------------------
def is_string(x: Any) -> bool:
    return isinstance(x, str)


def is_nonempty_string(x: Any) -> bool:
    return isinstance(x, str) and len(x) > 0


def is_bool(x: Any) -> bool:
    return isinstance(x, bool)


def is_int(x: Any) -> bool:
    # Exclude bool because bool is a subclass of int in Python.
    return isinstance(x, int) and not isinstance(x, bool)


def is_nonneg_int(x: Any) -> bool:
    return is_int(x) and x >= 0


def is_list(x: Any) -> bool:
    return isinstance(x, list)


def is_nonempty_list(x: Any) -> bool:
    return isinstance(x, list) and len(x) > 0


# -----------------------------------------------------------------------------
# Enumerations and pattern validators
# -----------------------------------------------------------------------------
def ensure_enum(value: Any, allowed: Iterable[str], field: str):
    if value not in allowed:
        raise APIError("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(set(allowed))}.")
    return value


_SCHOOL_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


def validate_school_year(value: Any) -> str:
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "school_year must be a string in 'YYYY-YYYY' format.")
    m = _SCHOOL_YEAR_RE.match(value)
    if not m:
        raise APIError("ERR_VALIDATION", "school_year must be in 'YYYY-YYYY' format.")
    y1, y2 = int(m.group(1)), int(m.group(2))
    if y2 != y1 + 1:
        raise APIError("ERR_VALIDATION", "school_year second year must be first year + 1.")
    return value


_NPI_RE = re.compile(r"^\d{10}$")


def validate_npi(value: Any) -> str:
    if not isinstance(value, str) or not _NPI_RE.match(value):
        raise APIError("ERR_VALIDATION", "npi must be a 10-digit string.")
    return value


# -----------------------------------------------------------------------------
# Pagination
# -----------------------------------------------------------------------------
def parse_pagination() -> tuple[int, int]:
    """Return (limit, offset) parsed from query string per global defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "limit must be an integer.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise APIError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise APIError("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(records: list, limit: int, offset: int) -> tuple[list, dict]:
    """Slice the list and produce the pagination meta block."""
    total = len(records)
    page = records[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# -----------------------------------------------------------------------------
# Datetime / date convenience
# -----------------------------------------------------------------------------
def parse_iso_or_400(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", f"Field '{field}' must be an ISO 8601 string.")
    try:
        return parse_iso(value)
    except Exception as exc:  # noqa: BLE001
        raise APIError("ERR_VALIDATION", f"Field '{field}' is not a valid ISO 8601 instant: {exc}") from exc


def parse_iso_date_or_400(value: Any, field: str):
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", f"Field '{field}' must be an ISO 8601 date.")
    try:
        return parse_iso_date(value)
    except Exception as exc:  # noqa: BLE001
        raise APIError("ERR_VALIDATION", f"Field '{field}' is not a valid date: {exc}") from exc


# -----------------------------------------------------------------------------
# Optimistic concurrency
# -----------------------------------------------------------------------------
def check_version_conflict(body: dict, record: dict):
    """If 'version' is supplied in the body and mismatches, raise. Otherwise pass."""
    if "version" not in body or body["version"] is None:
        return
    supplied = body["version"]
    if not is_int(supplied):
        raise APIError("ERR_VALIDATION", "version must be an integer.")
    if supplied != record.get("version"):
        raise APIError("ERR_VERSION_CONFLICT", "Supplied version does not match server version.")
