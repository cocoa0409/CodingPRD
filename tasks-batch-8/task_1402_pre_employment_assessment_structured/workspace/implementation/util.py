"""Shared utilities: datetime parsing/serialization, pagination, body parsing,
decimal rounding, and record serialization."""
import re
import uuid
from datetime import datetime, timezone

from flask import request

import db
from db import next_seq  # re-exported for route modules
from errors import err_invalid_request
from response import success_list

ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str) or not ISO_RE.match(value):
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body():
    """Return the JSON request body as a dict; ERR_INVALID_REQUEST otherwise.
    Empty bodies on action endpoints are treated as {}."""
    if request.data in (b"", None) or request.content_length == 0:
        return {}
    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def req_string(body, field, min_len=None):
    v = body.get(field)
    if not isinstance(v, str):
        raise err_invalid_request(f"{field} is required and must be a string")
    if min_len is not None and len(v) < min_len:
        raise err_invalid_request(f"{field} must be at least {min_len} characters")
    return v


def opt_string(body, field, default=None, min_len=None):
    v = body.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err_invalid_request(f"{field} must be a string")
    if min_len is not None and len(v) < min_len:
        raise err_invalid_request(f"{field} must be at least {min_len} characters")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} is required and must be an integer")
    if lo is not None and v < lo:
        raise err_invalid_request(f"{field} must be >= {lo}")
    if hi is not None and v > hi:
        raise err_invalid_request(f"{field} must be <= {hi}")
    return v


def opt_int(body, field, default=None, lo=None, hi=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, lo=lo, hi=hi)


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} is required and must be a number")
    return v


def paginate(records, sort_key=None):
    """Apply limit/offset per PRD §2.3. records: list of dicts (already sorted
    by created_at ascending via _seq ordering)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    total = len(records)
    page = records[offset:offset + limit]
    return success_list(page, limit, offset, total)


def filter_params(allowed):
    """Return dict of recognized filter params."""
    out = {}
    for f in allowed:
        v = request.args.get(f)
        if v is not None:
            out[f] = v
    return out


def sort_records(recs):
    """Sort by (created_at, _seq) ascending — list order per PRD §2.3."""
    return sorted(recs, key=lambda r: (r["_created"], r["_seq"]))


def bump(rec):
    """Mutation: version += 1 and updated_at refreshed (logical clock)."""
    rec["version"] += 1
    rec["updated_at"] = db.get_now()
