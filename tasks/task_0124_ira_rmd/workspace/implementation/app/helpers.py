"""Shared low-level helpers: id gen, pagination, OCC, type parsers."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Any

from flask import request

from .errors import err_validation, err_version_conflict

# Pagination defaults per scaffold response_envelope.pagination_defaults
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
        raise err_validation("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err_validation("offset must be an integer")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err_validation(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items: list[Any], limit: int, offset: int) -> list[Any]:
    return items[offset : offset + limit]


def require_json_object(*, allow_empty: bool = True) -> dict[str, Any]:
    raw = request.get_data(cache=True, as_text=True)
    if not raw or not raw.strip():
        if allow_empty:
            return {}
        raise err_validation("Request body is required")
    body = request.get_json(silent=True)
    if body is None:
        raise err_validation("Request body must be a JSON object")
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object")
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
            raise err_validation(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_validation(f"{field} must be a string")
    trimmed = value.strip()
    if len(trimmed) < min_len:
        raise err_validation(f"{field} must be a non-empty string after trim")
    if max_len is not None and len(trimmed) > max_len:
        raise err_validation(f"{field} must be at most {max_len} characters")
    if pattern is not None and not re.fullmatch(pattern, value):
        raise err_validation(f"{field} does not match the required format")
    return trimmed


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
            raise err_validation(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_validation(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_validation(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_validation(f"{field} must be <= {maximum}")
    return value


def assert_bool(value: Any, field: str, *, required: bool = True) -> bool | None:
    if value is None:
        if required:
            raise err_validation(f"{field} is required")
        return None
    if not isinstance(value, bool):
        raise err_validation(f"{field} must be a boolean")
    return value


def assert_enum(value: Any, field: str, allowed: list[str], *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise err_validation(f"{field} is required")
        return None
    if not isinstance(value, str) or value not in allowed:
        raise err_validation(f"{field} must be one of {sorted(allowed)}")
    return value


def parse_iso_date(value: Any, field: str, *, required: bool = True) -> date | None:
    if value is None:
        if required:
            raise err_validation(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_validation(f"{field} must be a YYYY-MM-DD date string")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise err_validation(f"{field} must be a valid YYYY-MM-DD date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise err_validation(f"{field} must be a valid YYYY-MM-DD date")


def occ_check(request_version: Any, stored_version: int) -> None:
    """Optimistic concurrency check — only enforced when client supplies `version`."""
    if request_version is None:
        return
    if isinstance(request_version, bool) or not isinstance(request_version, int):
        raise err_validation("version must be an integer")
    if request_version != stored_version:
        raise err_version_conflict()


def query_int(name: str, *, required: bool = False, minimum: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None:
        if required:
            raise err_validation(f"{name} query parameter is required")
        return None
    try:
        v = int(raw)
    except (TypeError, ValueError):
        raise err_validation(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"{name} must be >= {minimum}")
    return v


def query_date(name: str, *, required: bool = False) -> date | None:
    raw = request.args.get(name)
    if raw is None:
        if required:
            raise err_validation(f"{name} query parameter is required")
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise err_validation(f"{name} must be a valid YYYY-MM-DD date")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        raise err_validation(f"{name} must be a valid YYYY-MM-DD date")
