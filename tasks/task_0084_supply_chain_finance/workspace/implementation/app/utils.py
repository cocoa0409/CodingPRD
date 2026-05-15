"""Cross-cutting helpers: JSON body, pagination, version checks, ISO parsing."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from .errors import api_error


_UCC_RE = re.compile(r"^[0-9A-Z]{18}$")


def get_json_body() -> dict:
    if request.method in ("GET", "DELETE") and not request.data:
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise api_error("ERR_VALIDATION", "Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise api_error("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_str(body: dict, key: str) -> str:
    val = body.get(key)
    if not isinstance(val, str) or val == "":
        raise api_error("ERR_VALIDATION", f"Field '{key}' is required and must be a non-empty string")
    return val


def optional_str(body: dict, key: str, default: str | None = None) -> str | None:
    val = body.get(key, default)
    if val is None:
        return default
    if not isinstance(val, str):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be a string")
    return val


def require_int(body: dict, key: str) -> int:
    val = body.get(key)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise api_error("ERR_VALIDATION", f"Field '{key}' is required and must be an integer")
    return val


def optional_int(body: dict, key: str, default=None):
    val = body.get(key, default)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be an integer")
    return val


def optional_bool(body: dict, key: str, default: bool = False) -> bool:
    val = body.get(key, default)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be a boolean")
    return val


def optional_number(body: dict, key: str, default=None):
    val = body.get(key, default)
    if val is None:
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise api_error("ERR_VALIDATION", f"Field '{key}' must be a number")
    return float(val)


def require_number(body: dict, key: str) -> float:
    val = body.get(key)
    if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
        raise api_error("ERR_VALIDATION", f"Field '{key}' is required and must be a number")
    return float(val)


def parse_pagination():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise api_error("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise api_error("ERR_VALIDATION", "limit must be in [1, 100]")
    if offset < 0:
        raise api_error("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def page_slice(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


def check_version(body: dict, stored: dict, key: str = "version") -> None:
    """Optional optimistic-concurrency check. Mismatch → ERR_VERSION_CONFLICT."""
    if key in body and body[key] is not None:
        supplied = body[key]
        if isinstance(supplied, bool) or not isinstance(supplied, int):
            raise api_error("ERR_VERSION_CONFLICT", "version must equal stored version")
        if supplied != stored.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "Supplied version does not match stored version")


def parse_iso_datetime(value: str) -> datetime:
    if not isinstance(value, str):
        raise api_error("ERR_VALIDATION", "Datetime field must be a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise api_error("ERR_VALIDATION", f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_or_none(value):
    if value is None:
        return None
    return parse_iso_datetime(value)


def validate_ucc(code: str) -> None:
    if not _UCC_RE.match(code):
        raise api_error("ERR_VALIDATION", "unified_credit_code must match ^[0-9A-Z]{18}$")


def round_half_up_int(value) -> int:
    """Round-half-up to the nearest integer."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_decimals(value, places: int = 2) -> float:
    quant = Decimal("1") if places <= 0 else Decimal("1." + "0" * places)
    d = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return float(d)
