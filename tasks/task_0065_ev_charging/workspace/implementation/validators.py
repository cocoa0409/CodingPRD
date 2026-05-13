"""Input validation helpers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import request

from errors import raise_error


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
HHMM_RE = re.compile(r"^([01]\d|2[0-3])[0-5]\d$")
# Accept either "HHMM" or "HH:MM" — PRD §3.2 names the field start_hhmm/end_hhmm
# and describes "half-open {start_hhmm, end_hhmm} intervals within a calendar
# day" without pinning a serialization. We support both forms.
HHMM_COLON_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_error("ERR_VALIDATION", "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "request body must be an object")
    return body


def require_field(body: dict, key: str, kind: type | tuple = None):
    if key not in body:
        raise_error("ERR_VALIDATION", f"missing required field: {key}")
    value = body[key]
    if value is None:
        raise_error("ERR_VALIDATION", f"missing required field: {key}")
    if kind is not None and not isinstance(value, kind):
        raise_error("ERR_VALIDATION", f"field {key} has wrong type")
    return value


def require_str(body: dict, key: str, min_len: int = 1, max_len: int = 10_000):
    value = require_field(body, key, str)
    if len(value) < min_len or len(value) > max_len:
        raise_error("ERR_VALIDATION", f"field {key} length out of range")
    return value


def require_int(body: dict, key: str, min_value: int | None = None, max_value: int | None = None):
    value = body.get(key, None)
    if value is None:
        raise_error("ERR_VALIDATION", f"missing required field: {key}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_VALIDATION", f"field {key} must be integer")
    if min_value is not None and value < min_value:
        raise_error("ERR_VALIDATION", f"field {key} below minimum")
    if max_value is not None and value > max_value:
        raise_error("ERR_VALIDATION", f"field {key} above maximum")
    return value


def optional_int(body: dict, key: str, min_value: int | None = None, max_value: int | None = None):
    if key not in body or body[key] is None:
        return None
    return require_int(body, key, min_value=min_value, max_value=max_value)


def require_enum(body: dict, key: str, allowed: set[str]):
    value = require_field(body, key, str)
    if value not in allowed:
        raise_error("ERR_VALIDATION", f"field {key} must be one of {sorted(allowed)}")
    return value


def require_number(body: dict, key: str, min_value=None, max_value=None, max_frac_digits: int | None = None):
    value = body.get(key, None)
    if value is None:
        raise_error("ERR_VALIDATION", f"missing required field: {key}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error("ERR_VALIDATION", f"field {key} must be numeric")
    fvalue = float(value)
    if min_value is not None and fvalue < min_value:
        raise_error("ERR_VALIDATION", f"field {key} below minimum")
    if max_value is not None and fvalue > max_value:
        raise_error("ERR_VALIDATION", f"field {key} above maximum")
    if max_frac_digits is not None:
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            raise_error("ERR_VALIDATION", f"field {key} not a valid number")
        exp = -d.as_tuple().exponent if d.as_tuple().exponent < 0 else 0
        if exp > max_frac_digits:
            raise_error(
                "ERR_VALIDATION", f"field {key} exceeds {max_frac_digits} fractional digits"
            )
    return value


def get_pagination():
    """Return (limit, offset). limit defaults to 10 (range 1..100), offset to 0."""
    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        raise_error("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        raise_error("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_VALIDATION", "offset must be non-negative")
    return limit, offset


def paginate_list(items: list, limit: int, offset: int):
    total = len(items)
    page = items[offset : offset + limit]
    return page, total


def check_version(body: dict, stored: dict) -> None:
    """Optimistic concurrency check. If body carries `version`, compare to stored."""
    if "version" not in body or body["version"] is None:
        return
    supplied = body["version"]
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        raise_error("ERR_VALIDATION", "version must be integer")
    if supplied != stored.get("version"):
        raise_error("ERR_VERSION_CONFLICT", "version mismatch")
