"""Time formatting/parsing, id generation, envelope, pagination, shape helpers."""
import re
import secrets
import string
import uuid
from datetime import datetime, date, timezone

from errors import err_invalid_request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(16))


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T09:15:00.123Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field: str) -> datetime:
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise err_invalid_request(f"{field} must be an ISO date string YYYY-MM-DD")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err_invalid_request(f"{field} must be a valid calendar date")


# --- shape validation primitives ------------------------------------------

def require_field(body: dict, field: str):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise err_invalid_request(f"{field} is required")
    return body[field]


def req_str(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or not v.strip():
        raise err_invalid_request(f"{field} must be a non-empty string")
    return v


def opt_str(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err_invalid_request(f"{field} must be a string")
    return v


def req_int(body: dict, field: str) -> int:
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def opt_int(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    return v


def req_bool(body: dict, field: str) -> bool:
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v


def opt_bool(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v


def req_enum(body: dict, field: str, allowed) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body: dict, field: str, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def req_number(body: dict, field: str):
    v = require_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return v


def req_list(body: dict, field: str) -> list:
    v = require_field(body, field)
    if not isinstance(v, list):
        raise err_invalid_request(f"{field} must be an array")
    return v


# --- pagination ------------------------------------------------------------

def pagination_args(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0. Out-of-range clamps."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        offset = max(0, offset)
    return limit, offset
