"""Shared low-level helpers: id gen, pagination, OCC, type parsers."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from flask import request

from .errors import err_invalid_request, err_stale_data

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
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise err_invalid_request(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items: list[Any], limit: int, offset: int) -> list[Any]:
    return items[offset : offset + limit]


def require_json_object(*, allow_empty: bool = True) -> dict[str, Any]:
    raw = request.get_data(cache=True, as_text=True)
    if not raw or not raw.strip():
        if allow_empty:
            return {}
        raise err_invalid_request("Request body is required")
    body = request.get_json(silent=True)
    if body is None:
        raise err_invalid_request("Request body must be a JSON object")
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def assert_string(
    value: Any,
    field: str,
    *,
    required: bool = True,
    min_len: int = 1,
    max_len: int | None = None,
) -> str | None:
    if value is None:
        if required:
            raise err_invalid_request(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a string")
    trimmed = value.strip()
    if len(trimmed) < min_len:
        raise err_invalid_request(f"{field} must be a non-empty string after trim")
    if max_len is not None and len(trimmed) > max_len:
        raise err_invalid_request(f"{field} must be at most {max_len} characters")
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
            raise err_invalid_request(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid_request(f"{field} must be <= {maximum}")
    return value


def assert_number(
    value: Any,
    field: str,
    *,
    required: bool = True,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    """Accept int or float (not bool). Used for decimal hours."""
    if value is None:
        if required:
            raise err_invalid_request(f"{field} is required")
        return None
    if isinstance(value, bool):
        raise err_invalid_request(f"{field} must be a number")
    if not isinstance(value, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    v = float(value)
    if minimum is not None and v < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid_request(f"{field} must be <= {maximum}")
    return v


def assert_enum(value: Any, field: str, allowed: list[str], *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise err_invalid_request(f"{field} is required")
        return None
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return value


def parse_iso_date(value: Any, field: str, *, required: bool = True) -> date | None:
    if value is None:
        if required:
            raise err_invalid_request(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a YYYY-MM-DD date string")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise err_invalid_request(f"{field} must be a valid YYYY-MM-DD date")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise err_invalid_request(f"{field} must be a valid YYYY-MM-DD date")


def occ_check(request_version: Any, stored_version: int) -> None:
    """Optimistic concurrency check — only enforced when client supplies `version`."""
    if request_version is None:
        return
    if isinstance(request_version, bool) or not isinstance(request_version, int):
        raise err_invalid_request("version must be an integer")
    if request_version != stored_version:
        raise err_stale_data()


def round_half_up(value: Decimal | int | float) -> int:
    """Round to nearest whole cent using ROUND_HALF_UP."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
