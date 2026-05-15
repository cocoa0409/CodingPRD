"""Cross-cutting helpers: JSON parsing, pagination, version checks, decimals."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

from flask import request

from .errors import api_error


_CODE_RE = re.compile(r"^[A-Z0-9_-]+$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def get_json_body() -> dict:
    """Return parsed JSON body as a dict; empty body returns {}."""
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise api_error("ERR_VALIDATION_FAILED", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise api_error("ERR_VALIDATION_FAILED", "Request body must be a JSON object")
    return body


def parse_pagination():
    """Read limit/offset from query string, applying defaults & bounds."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION_FAILED", "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION_FAILED", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise api_error("ERR_VALIDATION_FAILED", "limit must be in [1, 100]")
    if offset < 0:
        raise api_error("ERR_VALIDATION_FAILED", "offset must be >= 0")
    return limit, offset


def page_slice(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def check_version(body: dict, stored: dict, key: str = "version") -> None:
    """If body contains `version`, enforce equality with stored.version."""
    if key in body and body[key] is not None:
        supplied = body[key]
        if not isinstance(supplied, int):
            raise api_error("ERR_VERSION_CONFLICT", "version must equal stored version")
        if supplied != stored.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "Supplied version does not match stored version")


def check_version_query(stored: dict) -> None:
    """Check optional ?version= query param too (where no body)."""
    if "version" in request.args:
        raw = request.args.get("version")
        try:
            supplied = int(raw)
        except (TypeError, ValueError):
            raise api_error("ERR_VERSION_CONFLICT", "version must equal stored version")
        if supplied != stored.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "Supplied version does not match stored version")


def parse_iso_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise api_error("ERR_VALIDATION_FAILED", "Datetime field must be a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise api_error("ERR_VALIDATION_FAILED", f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_or_none(value: Any) -> datetime | None:
    if value is None:
        return None
    return parse_iso_datetime(value)


def to_decimal(val: Any, field: str, err: str = "ERR_VALIDATION_FAILED") -> Decimal:
    if val is None:
        raise api_error(err, f"{field} is required")
    try:
        if isinstance(val, bool):
            raise InvalidOperation()
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        raise api_error(err, f"{field} must be a number")


def decimal_places(d: Decimal) -> int:
    """Return number of fractional decimal places in `d` (0 for integers)."""
    # Normalize away trailing zeros but ensure we count actual stored precision
    sign, digits, exp = d.as_tuple()
    if exp >= 0:
        return 0
    return -exp


def check_max_decimals(d: Decimal, max_dp: int, field: str, err: str = "ERR_VALIDATION_FAILED") -> None:
    if decimal_places(d) > max_dp:
        raise api_error(err, f"{field} must have at most {max_dp} decimal places")


def round_half_up(d: Decimal, places: int) -> Decimal:
    quant = Decimal(1).scaleb(-places)  # 10**-places
    return d.quantize(quant, rounding=ROUND_HALF_UP)


def decimal_to_number(d: Decimal):
    """Serialize Decimal to JSON-friendly value (float)."""
    if d is None:
        return None
    return float(d)


def validate_code(value: str, field: str = "code") -> None:
    if not isinstance(value, str) or not _CODE_RE.fullmatch(value):
        raise api_error("ERR_VALIDATION_FAILED", f"{field} must match [A-Z0-9_-]+")


def validate_country(value: str) -> None:
    if not isinstance(value, str) or not _COUNTRY_RE.fullmatch(value):
        raise api_error("ERR_VALIDATION_FAILED", "country_code must be 2 uppercase letters")


def validate_currency(value: str) -> None:
    if not isinstance(value, str) or not _CURRENCY_RE.fullmatch(value):
        raise api_error("ERR_VALIDATION_FAILED", "functional_currency must be 3 uppercase letters")


def require_str(body: dict, key: str, min_len: int = 1, max_len: int | None = None) -> str:
    val = body.get(key)
    if not isinstance(val, str):
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be a string")
    stripped = val.strip() if min_len > 0 else val
    if min_len > 0 and len(stripped) < min_len:
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be at least {min_len} chars")
    if max_len is not None and len(val) > max_len:
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be at most {max_len} chars")
    return val


def require_enum(body: dict, key: str, options: set[str]) -> str:
    val = body.get(key)
    if val not in options:
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be one of {sorted(options)}")
    return val


def require_int(body: dict, key: str, min_val: int | None = None, max_val: int | None = None) -> int:
    val = body.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be an integer")
    if min_val is not None and val < min_val:
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be >= {min_val}")
    if max_val is not None and val > max_val:
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be <= {max_val}")
    return val


def require_bool(body: dict, key: str) -> bool:
    val = body.get(key)
    if not isinstance(val, bool):
        raise api_error("ERR_VALIDATION_FAILED", f"{key} must be a boolean")
    return val
