"""Shared helpers: entity bookkeeping, pagination, body parsing, validation,
serialization, money rounding, and ISO-8601 datetime parsing.

Common fields (PRD §2.4): most entities carry id/created_at/updated_at/version
(version starts at 1, increments on every mutation including cascades).
Two entities are leaner immutable ledger events: DeductionLine and
CarrierFeedRecord (id + created_at only).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from flask import request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION_PAGINATION,
)

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ----------------------------------------------------------------------------
# Entity bookkeeping
# ----------------------------------------------------------------------------
def new_common_fields() -> dict:
    """id/created_at/updated_at/version for a full (mutable, versioned) entity."""
    now = db.now_iso()
    return {
        "id": db.new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def new_lean_fields() -> dict:
    """id + created_at only — for DeductionLine and CarrierFeedRecord."""
    return {
        "id": db.new_uuid(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a versioned entity."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ----------------------------------------------------------------------------
# Pagination + listing
# ----------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit", str(DEFAULT_LIMIT))
    offset = request.args.get("offset", str(DEFAULT_OFFSET))
    try:
        limit_i = int(limit)
        offset_i = int(offset)
    except (TypeError, ValueError):
        raise APIError(ERR_VALIDATION_PAGINATION, 422, "limit/offset must be integers")
    if limit_i < MIN_LIMIT or limit_i > MAX_LIMIT:
        raise APIError(ERR_VALIDATION_PAGINATION, 422, "limit must be in [1,100]")
    if offset_i < 0:
        raise APIError(ERR_VALIDATION_PAGINATION, 422, "offset must be >= 0")
    return limit_i, offset_i


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def order_by_created(items: Iterable[dict]) -> list:
    """Ascending creation order (PRD §2.3), monotonic _seq as tiebreaker."""
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("_seq", 0)))


# ----------------------------------------------------------------------------
# Body parsing + validation
# ----------------------------------------------------------------------------
def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Body must be a JSON object")
    return body


def require_fields(body: dict, fields) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 422, f"Missing required field: {f}")


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_str(v: Any) -> bool:
    return isinstance(v, str)


def is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def require_int(body: dict, field: str) -> int:
    v = body.get(field)
    if not is_int(v):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be an integer")
    return v


def require_nonneg_int(body: dict, field: str) -> int:
    v = require_int(body, field)
    if v < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be >= 0")
    return v


def require_str(body: dict, field: str) -> str:
    v = body.get(field)
    if not is_str(v) or v == "":
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be a non-empty string")
    return v


def require_enum(body: dict, field: str, allowed) -> str:
    v = body.get(field)
    if not is_str(v) or v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, 422, f"{field} must be one of {sorted(allowed)}")
    return v


# ----------------------------------------------------------------------------
# Money / rounding (PRD §2.6 round half up)
# ----------------------------------------------------------------------------
def round_half_up(value) -> int:
    """Round to a whole number using ROUND_HALF_UP (PRD §2.6)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# Datetime parsing
# ----------------------------------------------------------------------------
def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 instant to an aware UTC datetime; raise APIError on bad input."""
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "datetime must be an ISO-8601 string")
    s = value.strip()
    if not s:
        raise APIError(ERR_INVALID_REQUEST, 422, "datetime must be a non-empty string")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 422, "datetime must be a valid ISO-8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_of(dt: datetime):
    """Calendar date (UTC) of an aware datetime."""
    return dt.astimezone(timezone.utc).date()


def iso_date_str(d) -> str:
    """Render a date as ISO 8601 date string (YYYY-MM-DD)."""
    return d.isoformat()


# ----------------------------------------------------------------------------
# Serialization (drop internal-only keys)
# ----------------------------------------------------------------------------
def serialize(entity: dict) -> dict:
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(items) -> list:
    return [serialize(e) for e in items]
