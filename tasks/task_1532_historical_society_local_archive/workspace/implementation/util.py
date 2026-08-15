"""Request parsing / validation helpers (priority-3 body shape checks)."""

from __future__ import annotations

import json
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PAGINATION_PARAMETERS,
)


# ---------------------------------------------------------------------------
# JSON body
# ---------------------------------------------------------------------------

def get_json_body() -> dict:
    """Parse the request body as JSON. Absent body -> {}. Non-object -> 400.

    Numbers keep their exact posted decimal precision (parse_float=Decimal) so
    environmental threshold comparisons are exact (PRD §2.9).
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validators — all raise ERR_INVALID_REQUEST (priority 3)
# ---------------------------------------------------------------------------

def _fail(field: str, why: str):
    raise_err(ERR_INVALID_REQUEST, f"Field '{field}': {why}")


def require_field(body: dict, field: str):
    if field not in body or body[field] is None:
        _fail(field, "is required")
    return body[field]


def opt_field(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_str(body: dict, field: str, required: bool = True, default=None):
    if field not in body or body[field] is None:
        if required:
            _fail(field, "is required")
        return default
    v = body[field]
    if not isinstance(v, str):
        _fail(field, "must be a string")
    return v


def as_bool(body: dict, field: str, required: bool = False, default=None):
    if field not in body or body[field] is None:
        if required:
            _fail(field, "is required")
        return default
    v = body[field]
    if not isinstance(v, bool):
        _fail(field, "must be a boolean")
    return v


def as_int(body: dict, field: str, required: bool = True, default=None,
           minimum: int | None = None, maximum: int | None = None):
    if field not in body or body[field] is None:
        if required:
            _fail(field, "is required")
        return default
    v = body[field]
    if isinstance(v, bool):
        _fail(field, "must be an integer")
    if isinstance(v, Decimal):
        if v != v.to_integral_value():
            _fail(field, "must be an integer")
        v = int(v)
    if not isinstance(v, int):
        _fail(field, "must be an integer")
    if minimum is not None and v < minimum:
        _fail(field, f"must be >= {minimum}")
    if maximum is not None and v > maximum:
        _fail(field, f"must be <= {maximum}")
    return v


def as_number(body: dict, field: str, required: bool = True, default=None):
    """Numeric field -> Decimal at exact posted precision."""
    if field not in body or body[field] is None:
        if required:
            _fail(field, "is required")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        _fail(field, "must be a number")
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def as_enum(body: dict, field: str, allowed: set | list, required: bool = True, default=None):
    v = as_str(body, field, required=required, default=default)
    if v is None:
        return None
    if v not in allowed:
        _fail(field, f"must be one of {sorted(allowed)}")
    return v


def as_str_list(body: dict, field: str, required: bool = True):
    if field not in body or body[field] is None:
        if required:
            _fail(field, "is required")
        return None
    v = body[field]
    if not isinstance(v, list):
        _fail(field, "must be an array")
    for el in v:
        if not isinstance(el, str):
            _fail(field, "must contain only strings")
    return v


def check_no_duplicates(values: list, field: str = "item_ids"):
    if len(set(values)) != len(values):
        _fail(field, "must not contain duplicate entries")


# ---------------------------------------------------------------------------
# Date / time parsing
# ---------------------------------------------------------------------------

def parse_iso8601(value, field: str = "timestamp") -> datetime:
    """Parse an ISO 8601 instant; naive values are interpreted as UTC."""
    if not isinstance(value, str):
        _fail(field, "must be an ISO 8601 timestamp string")
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        _fail(field, "must be an ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso8601_opt(body: dict, field: str) -> datetime | None:
    """Optional nullable ISO instant; returns None when absent/null."""
    if field not in body or body[field] is None:
        return None
    return parse_iso8601(body[field], field)


def parse_date_field(value, field: str) -> date:
    if not isinstance(value, str):
        _fail(field, "must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        _fail(field, "must be a YYYY-MM-DD date")


def parse_time_field(value, field: str) -> int:
    """Parse HH:MM 24h time; returns minutes since midnight."""
    if not isinstance(value, str):
        _fail(field, "must be an HH:MM time string")
    try:
        t = datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        _fail(field, "must be an HH:MM time")
    return t.hour * 60 + t.minute


# ---------------------------------------------------------------------------
# Pagination (priority 3; ERR_INVALID_PAGINATION_PARAMETERS)
# ---------------------------------------------------------------------------

def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    def _bad():
        raise_err(
            ERR_INVALID_PAGINATION_PARAMETERS,
            "limit must be an integer in 1..100 and offset an integer >= 0",
        )

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit.strip())
        except (ValueError, AttributeError):
            _bad()
        if limit < 1 or limit > 100:
            _bad()
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset.strip())
        except (ValueError, AttributeError):
            _bad()
        if offset < 0:
            _bad()
    return limit, offset


def paginate(items: list) -> tuple[list, int, int, int]:
    """Sort by (created_at, insertion seq) and apply limit/offset.

    Returns (page, limit, offset, total_count).
    """
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def public_view(entity: dict) -> dict:
    """Strip internal (underscore-prefixed) fields from a stored entity."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
