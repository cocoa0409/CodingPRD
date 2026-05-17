"""Shared low-level helpers: id generation, pagination parsing, OCC checks, parsers."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import request

from .errors import err_invalid_input, err_version_conflict

# Pagination defaults match scaffold response_envelope.pagination_defaults.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def new_uuid() -> str:
    return str(uuid.uuid4())


def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise err_invalid_input("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err_invalid_input("offset must be an integer")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err_invalid_input(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise err_invalid_input("offset must be >= 0")
    return limit, offset


def paginate(items: list[Any], limit: int, offset: int) -> list[Any]:
    return items[offset : offset + limit]


def require_json_object() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_input("Request body must be a JSON object")
    return body


def assert_string(
    value: Any,
    field: str,
    *,
    required: bool = True,
    min_len: int = 1,
    max_len: int | None = None,
    pattern: str | None = None,
) -> str | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_invalid_input(f"{field} must be a string")
    length = len(value)
    if length < min_len:
        raise err_invalid_input(f"{field} must be at least {min_len} character(s)")
    if max_len is not None and length > max_len:
        raise err_invalid_input(f"{field} must be at most {max_len} character(s)")
    if pattern is not None and not re.fullmatch(pattern, value):
        raise err_invalid_input(f"{field} does not match the required format")
    return value


def assert_integer(
    value: Any,
    field: str,
    *,
    required: bool = True,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_input(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid_input(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid_input(f"{field} must be <= {maximum}")
    return value


def assert_number(
    value: Any,
    field: str,
    *,
    required: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_input(f"{field} must be a number")
    val = float(value)
    if minimum is not None and val < minimum:
        raise err_invalid_input(f"{field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err_invalid_input(f"{field} must be <= {maximum}")
    return val


def assert_bool(value: Any, field: str, *, required: bool = True) -> bool | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, bool):
        raise err_invalid_input(f"{field} must be a boolean")
    return value


def assert_enum(value: Any, field: str, allowed: list[str], *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_input(f"{field} must be one of {sorted(allowed)}")
    return value


def assert_array(value: Any, field: str, *, required: bool = True) -> list[Any] | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, list):
        raise err_invalid_input(f"{field} must be an array")
    return value


def parse_iso8601(value: Any, field: str, *, required: bool = True) -> datetime | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_invalid_input(f"{field} must be an ISO 8601 timestamp string")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err_invalid_input(f"{field} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise err_invalid_input(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_invalid_input(f"{field} must be a YYYY-MM-DD date string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise err_invalid_input(f"{field} must be a valid YYYY-MM-DD date")
    return value


def occ_check(request_version: Any, stored_version: int) -> None:
    """Optimistic concurrency: only checked when `version` is present in the body."""
    if request_version is None:
        return
    if isinstance(request_version, bool) or not isinstance(request_version, int):
        raise err_invalid_input("version must be an integer")
    if request_version != stored_version:
        raise err_version_conflict()
