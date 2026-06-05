"""Shared helpers: common-field stamping, time parsing, pagination, validation."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from flask import request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
)


# ---------------------------------------------------------------------------
# common system fields (PRD §2.5)
# ---------------------------------------------------------------------------
def stamp_create(record: Dict[str, Any], versioned: bool = True) -> Dict[str, Any]:
    """Attach id + system fields on creation. versioned=False for append-only
    audit records (ReeferReading, EquipmentInterchangeReceipt) which carry only
    id + created_at."""
    now = db.wall_now_iso()
    record["id"] = db.new_uuid()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record: Dict[str, Any]) -> None:
    """Refresh updated_at and bump version on a versioned entity mutation."""
    record["updated_at"] = db.wall_now_iso()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# datetime parsing / comparison (millisecond resolution, PRD §2.4)
# ---------------------------------------------------------------------------
def parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Raises APIError(ERR_INVALID_REQUEST) on malformed input.
    """
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "datetime must be a string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, 422, f"malformed datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_dt() -> datetime:
    return parse_dt(db.clock_now())


def format_dt(dt: datetime) -> str:
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def minutes(n: int) -> timedelta:
    return timedelta(minutes=n)


# ---------------------------------------------------------------------------
# request body / field validation (priority 5, ERR_INVALID_REQUEST 422)
# ---------------------------------------------------------------------------
def get_body() -> Dict[str, Any]:
    """Return the JSON body as a dict; tolerate an empty body as {}."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "body must be a JSON object")
    return data


def bad_request(msg: str) -> APIError:
    return APIError(ERR_INVALID_REQUEST, 422, msg)


def require_present(body: Dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        raise bad_request(f"missing required field: {field}")
    return body[field]


def require_str(body: Dict[str, Any], field: str, non_empty: bool = True) -> str:
    v = require_present(body, field)
    if not isinstance(v, str):
        raise bad_request(f"{field} must be a string")
    if non_empty and v.strip() == "":
        raise bad_request(f"{field} must be non-empty")
    return v


def require_int(body: Dict[str, Any], field: str) -> int:
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"{field} must be an integer")
    return v


def require_number(body: Dict[str, Any], field: str) -> float:
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad_request(f"{field} must be a number")
    return float(v)


def require_enum(body: Dict[str, Any], field: str, allowed: set) -> str:
    v = require_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise bad_request(f"{field} must be one of {sorted(allowed)}")
    return v


def optional_bool(body: Dict[str, Any], field: str, default: bool = False) -> bool:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise bad_request(f"{field} must be a boolean")
    return v


IMO_RE = re.compile(r"^\d{7}$")


# ---------------------------------------------------------------------------
# pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0
# ---------------------------------------------------------------------------
def parse_pagination() -> Tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(records: List[Dict[str, Any]], serializer) -> Tuple[List[Dict[str, Any]], int, int, int]:
    """Sort by created_at asc (tie-break _seq), apply limit/offset, serialize.

    Returns (items, limit, offset, total_count).
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return [serializer(r) for r in page], limit, offset, total
