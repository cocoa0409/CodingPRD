"""Shared helpers: time parsing, rounding, decimal helpers, pagination."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional

from flask import request

from errors import ERR_VALIDATION, raise_api_error


# ---------- time / iso parsing ----------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:?\d{2})$"
)


def parse_iso8601_utc(s: Any) -> dt.datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Accepts trailing 'Z' or +HH:MM. Raises ERR_VALIDATION on bad input.
    """
    if not isinstance(s, str) or not s:
        raise_api_error(ERR_VALIDATION, "Expected an ISO 8601 datetime string.")
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        d = dt.datetime.fromisoformat(s2)
    except ValueError:
        raise_api_error(ERR_VALIDATION, f"Invalid ISO 8601 datetime: {s}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def iso_z(d: dt.datetime) -> str:
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    d_utc = d.astimezone(dt.timezone.utc)
    return d_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d_utc.microsecond // 1000:03d}Z"


def to_zone(d: dt.datetime, tz_name: str) -> dt.datetime:
    """Convert UTC datetime into the named IANA timezone."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:
        tz = dt.timezone.utc
    return d.astimezone(tz)


def calendar_day(d: dt.datetime, tz_name: str) -> dt.date:
    """Return the local calendar date in the given timezone."""
    return to_zone(d, tz_name).date()


# ---------- rounding ----------

def round_half_up(value, places: int = 0):
    """Round half-up to `places` decimal places. Returns int when places == 0,
    else float for ease of JSON-ability."""
    if value is None:
        return value
    quant = Decimal(10) ** (-places)
    try:
        q = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise_api_error(ERR_VALIDATION, f"Cannot round value: {value!r}")
    if places <= 0:
        return int(q)
    return float(q)


# ---------- payload helpers ----------

def get_json_body() -> dict:
    """Return JSON body as dict; raise ERR_VALIDATION when malformed or non-object."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_api_error(ERR_VALIDATION, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_api_error(ERR_VALIDATION, "JSON body must be an object.")
    return body


def require_str(body: dict, key: str, *, min_len: int = 1, max_len: int = 10_000) -> str:
    v = body.get(key)
    if not isinstance(v, str):
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be a string.")
    if len(v) < min_len or len(v) > max_len:
        raise_api_error(
            ERR_VALIDATION,
            f"Field '{key}' length must be in [{min_len}, {max_len}].",
        )
    return v


def optional_str(body: dict, key: str, *, min_len: int = 1, max_len: int = 10_000) -> Optional[str]:
    if key not in body or body[key] is None:
        return None
    return require_str(body, key, min_len=min_len, max_len=max_len)


def require_enum(body: dict, key: str, valid: set[str]) -> str:
    v = body.get(key)
    if not isinstance(v, str) or v not in valid:
        raise_api_error(
            ERR_VALIDATION,
            f"Field '{key}' must be one of {sorted(valid)}.",
        )
    return v


def optional_enum(body: dict, key: str, valid: set[str]) -> Optional[str]:
    if key not in body or body[key] is None:
        return None
    return require_enum(body, key, valid)


def require_int(body: dict, key: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be an integer.")
    if minimum is not None and v < minimum:
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be <= {maximum}.")
    return v


def optional_int(body: dict, key: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    if key not in body or body[key] is None:
        return None
    return require_int(body, key, minimum=minimum, maximum=maximum)


def require_number(body: dict, key: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    v = body.get(key)
    if isinstance(v, bool):
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be a number.")
    if not isinstance(v, (int, float)):
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be a number.")
    v = float(v)
    if minimum is not None and v < minimum:
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise_api_error(ERR_VALIDATION, f"Field '{key}' must be <= {maximum}.")
    return v


def optional_number(body: dict, key: str, *, minimum: Optional[float] = None, maximum: Optional[float] = None) -> Optional[float]:
    if key not in body or body[key] is None:
        return None
    return require_number(body, key, minimum=minimum, maximum=maximum)


def optional_datetime(body: dict, key: str) -> Optional[dt.datetime]:
    if key not in body or body[key] is None:
        return None
    return parse_iso8601_utc(body[key])


def require_datetime(body: dict, key: str) -> dt.datetime:
    if key not in body or body[key] is None:
        raise_api_error(ERR_VALIDATION, f"Field '{key}' is required.")
    return parse_iso8601_utc(body[key])


# ---------- pagination ----------

def parse_pagination() -> tuple[int, int]:
    """Parse `limit` and `offset` from query string with defaults/min/max per PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_api_error(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise_api_error(ERR_VALIDATION, "limit must be in [1, 100].")

    offset = 0
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_api_error(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            raise_api_error(ERR_VALIDATION, "offset must be >= 0.")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


# ---------- optimistic concurrency ----------

def check_version(body: dict, current: dict) -> None:
    """If body.version is supplied, it must equal current.version."""
    if "version" not in body or body["version"] is None:
        return
    v = body["version"]
    if not isinstance(v, int) or isinstance(v, bool):
        raise_api_error(ERR_VALIDATION, "version must be an integer.")
    if v != current.get("version", 1):
        from errors import ERR_VERSION_CONFLICT  # local import to avoid cycle

        raise_api_error(
            ERR_VERSION_CONFLICT,
            f"Version mismatch: provided {v}, current {current.get('version')}",
        )


# ---------- hex regex ----------

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
CMTY_CODE_RE = re.compile(r"^CMTY-[0-9]{3,6}$")
