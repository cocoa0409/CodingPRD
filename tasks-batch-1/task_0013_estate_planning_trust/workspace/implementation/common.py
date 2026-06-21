"""Shared utilities: id minting, timestamp formatting, body parsing helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from errors import APIError, ERR_INVALID_REQUEST


def new_id() -> str:
    """Lowercase hyphenated UUID, no resource-type prefix."""
    return str(uuid.uuid4())


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_common_fields(entity: dict, now: datetime) -> None:
    """Set common fields on a freshly created entity."""
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1


def touch(entity: dict, now: datetime) -> None:
    """Refresh updated_at + bump version on a mutation."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 0) + 1


def parse_iso_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, f"{field_name} must be an ISO 8601 string.", 400)
    raw = value
    # Accept trailing Z
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise APIError(ERR_INVALID_REQUEST, f"{field_name} is not a valid ISO 8601 datetime.", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_field(body: dict, field: str) -> Any:
    if field not in body:
        raise APIError(ERR_INVALID_REQUEST, f"Required field '{field}' is missing.", 400)
    return body[field]


def require_enum(body: dict, field: str, allowed: set[str]) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise APIError(
            ERR_INVALID_REQUEST,
            f"{field} must be one of {sorted(allowed)}; got {v!r}.",
            400,
        )
    return v


def require_int(body: dict, field: str, *, min_value: Optional[int] = None, strict_positive: bool = False) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be an integer.", 400)
    if strict_positive and v <= 0:
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be strictly positive.", 400)
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be >= {min_value}.", 400)
    return v


def require_string(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be a string.", 400)
    return v


def optional_string(body: dict, field: str) -> Optional[str]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be a string if provided.", 400)
    return v


def optional_int(body: dict, field: str) -> Optional[int]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, f"{field} must be an integer if provided.", 400)
    return v


def get_body() -> dict:
    """Return the JSON body or {} if absent. Reject non-object payloads."""
    if not _has_body():
        return {}
    body = _silent_json()
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    return body


def _has_body() -> bool:
    from flask import request
    return bool(request.data)


def _silent_json():
    from flask import request
    return request.get_json(silent=True)


def pagination_params() -> tuple[int, int]:
    """Parse limit/offset query params. PRD §2.3."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "limit must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise APIError(ERR_INVALID_REQUEST, "limit must be between 1 and 100.", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "offset must be an integer.", 400)
        if offset < 0:
            raise APIError(ERR_INVALID_REQUEST, "offset must be >= 0.", 400)
    return limit, offset
