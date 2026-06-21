"""Shared utilities: id minting, timestamp formatting, body parsing helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from flask import request

from errors import APIError, ERR_VALIDATION


def new_id() -> str:
    """Lowercase hyphenated UUID, no resource-type prefix. PRD §2.4."""
    return str(uuid.uuid4())


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits + 'Z'. PRD §2.4."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_common_fields(entity: dict, now: datetime) -> None:
    """Set common system fields on a freshly created mutable entity. PRD §2.4."""
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1


def stamp_immutable(entity: dict, now: datetime) -> None:
    """Append-only audit records carry only id + created_at. PRD §2.4."""
    entity.setdefault("id", new_id())
    entity["created_at"] = now


def touch(entity: dict, now: datetime) -> None:
    """Refresh updated_at + bump version on a mutation. PRD §2.4."""
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 0) + 1


# ----- body parsing / validation helpers (ERR_VALIDATION = 400) -----

def get_body() -> dict:
    """Return the JSON body or {} if absent. Reject non-object payloads."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_VALIDATION, "Request body must be a JSON object.", 400)
    return body


def require_field(body: dict, field: str) -> Any:
    if field not in body or body[field] is None:
        raise APIError(ERR_VALIDATION, f"Required field '{field}' is missing.", 400)
    return body[field]


def require_string(body: dict, field: str, *, max_len: Optional[int] = None, non_empty: bool = False) -> str:
    v = require_field(body, field)
    if not isinstance(v, str):
        raise APIError(ERR_VALIDATION, f"{field} must be a string.", 400)
    if non_empty and v.strip() == "":
        raise APIError(ERR_VALIDATION, f"{field} must be non-empty.", 400)
    if max_len is not None and len(v) > max_len:
        raise APIError(ERR_VALIDATION, f"{field} must be at most {max_len} characters.", 400)
    return v


def require_enum(body: dict, field: str, allowed: Iterable[str]) -> str:
    allowed_set = set(allowed)
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed_set:
        raise APIError(
            ERR_VALIDATION,
            f"{field} must be one of {sorted(allowed_set)}; got {v!r}.",
            400,
        )
    return v


def require_int(
    body: dict,
    field: str,
    *,
    min_value: Optional[int] = None,
    strict_positive: bool = False,
) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_VALIDATION, f"{field} must be an integer.", 400)
    if strict_positive and v <= 0:
        raise APIError(ERR_VALIDATION, f"{field} must be strictly positive.", 400)
    if min_value is not None and v < min_value:
        raise APIError(ERR_VALIDATION, f"{field} must be >= {min_value}.", 400)
    return v


def optional_int(
    body: dict,
    field: str,
    *,
    default: Optional[int] = None,
    min_value: Optional[int] = None,
) -> Optional[int]:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_VALIDATION, f"{field} must be an integer if provided.", 400)
    if min_value is not None and v < min_value:
        raise APIError(ERR_VALIDATION, f"{field} must be >= {min_value}.", 400)
    return v


def require_number(body: dict, field: str, *, min_value: Optional[float] = None) -> float:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_VALIDATION, f"{field} must be a number.", 400)
    if min_value is not None and v < min_value:
        raise APIError(ERR_VALIDATION, f"{field} must be >= {min_value}.", 400)
    return float(v)


def optional_number(
    body: dict,
    field: str,
    *,
    default: float = 0.0,
    min_value: Optional[float] = None,
    max_value_exclusive: Optional[float] = None,
) -> float:
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_VALIDATION, f"{field} must be a number if provided.", 400)
    if min_value is not None and v < min_value:
        raise APIError(ERR_VALIDATION, f"{field} must be >= {min_value}.", 400)
    if max_value_exclusive is not None and v >= max_value_exclusive:
        raise APIError(ERR_VALIDATION, f"{field} must be < {max_value_exclusive}.", 400)
    return float(v)


def require_bool(body: dict, field: str, *, default: Optional[bool] = None) -> bool:
    if field not in body or body[field] is None:
        if default is None:
            raise APIError(ERR_VALIDATION, f"Required field '{field}' is missing.", 400)
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise APIError(ERR_VALIDATION, f"{field} must be a boolean.", 400)
    return v


def require_id(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or v.strip() == "":
        raise APIError(ERR_VALIDATION, f"{field} must be a non-empty id string.", 400)
    return v


def optional_id(body: dict, field: str) -> Optional[str]:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise APIError(ERR_VALIDATION, f"{field} must be an id string if provided.", 400)
    return v


def parse_iso_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise APIError(ERR_VALIDATION, f"{field_name} must be an ISO 8601 string.", 400)
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise APIError(ERR_VALIDATION, f"{field_name} is not a valid ISO 8601 datetime.", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_datetime(body: dict, field: str) -> datetime:
    return parse_iso_datetime(require_field(body, field), field)


def pagination_params() -> tuple:
    """Parse limit/offset query params. PRD §2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, "limit must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise APIError(ERR_VALIDATION, "limit must be between 1 and 100.", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError(ERR_VALIDATION, "offset must be an integer.", 400)
        if offset < 0:
            raise APIError(ERR_VALIDATION, "offset must be >= 0.", 400)
    return limit, offset


def paginate_and_sort(items: list, limit: int, offset: int) -> tuple:
    """Sort by created_at ASC (PRD §2.3) then slice. Returns (page, total_count)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
