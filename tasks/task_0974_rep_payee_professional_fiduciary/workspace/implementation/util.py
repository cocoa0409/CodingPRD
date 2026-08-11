"""Shared utilities: UUIDs, timestamps, dates, decimal math, pagination."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ERR_INVALID_REQUEST, err


def new_id():
    return str(uuid.uuid4())


def iso_ts(dt):
    """ISO 8601 UTC with 3 fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_date(s, field):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO date YYYY-MM-DD")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid calendar date")


def parse_month(s, field):
    if not isinstance(s, str) or not _MONTH_RE.match(s):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be YYYY-MM")
    y, m = s.split("-")
    mi = int(m)
    if mi < 1 or mi > 12:
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' has invalid month")
    return s  # store as canonical string


def parse_datetime(s, field):
    if not isinstance(s, str):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO 8601 datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        iso = txt[:-1] + "+00:00"
    else:
        iso = txt
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(d, n):
    return d + timedelta(days=n)


def round_half_up_cents(value):
    """value: Decimal or numeric — round to whole cents via ROUND_HALF_UP -> int."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- body parsing helpers -------------------------------------------------

def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def get_string(body, field, required=True):
    if field not in body:
        if required:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
        return None
    v = body[field]
    if v is None:
        if required:
            raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must not be null")
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a string")
    return v


def get_int(body, field, required=True, min_value=None, allow_null=False):
    if field not in body:
        if required:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
        return None
    v = body[field]
    if v is None:
        if allow_null or not required:
            return None
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must not be null")
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be >= {min_value}")
    return v


def get_bool(body, field, required=True):
    if field not in body:
        if required:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field '{field}'")
        return None
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be a boolean")
    return v


def get_enum(body, field, choices, required=True):
    v = get_string(body, field, required=required)
    if v is None:
        return None
    if v not in choices:
        raise err(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be one of {sorted(choices)}")
    return v


def reject_unexpected(body, allowed_fields):
    extras = [k for k in body.keys() if k not in allowed_fields]
    if extras:
        raise err(ERR_INVALID_REQUEST, 400, f"Unexpected field(s): {', '.join(sorted(extras))}")


# --- pagination -----------------------------------------------------------

def parse_pagination():
    from flask import request
    args = request.args

    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")

    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")

    return limit, offset
