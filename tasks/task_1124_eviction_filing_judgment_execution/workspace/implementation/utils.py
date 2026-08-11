"""Request parsing / validation helpers. All shape failures raise ERR_VALIDATION (400)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _verr(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def body_json():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        _verr("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    if not isinstance(v, str) or v == "":
        _verr(f"{name} must be a non-empty string")
    return v


def v_int(b, name, required=True, min_exclusive=None, min_inclusive=None):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    if not is_int(v):
        _verr(f"{name} must be an integer")
    if min_exclusive is not None and not (v > min_exclusive):
        _verr(f"{name} must be > {min_exclusive}")
    if min_inclusive is not None and not (v >= min_inclusive):
        _verr(f"{name} must be >= {min_inclusive}")
    return v


def v_bool(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    if not isinstance(v, bool):
        _verr(f"{name} must be a boolean")
    return v


def v_enum(b, name, allowed, required=True):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    if not isinstance(v, str) or v not in allowed:
        _verr(f"{name} must be one of {sorted(allowed)}")
    return v


def parse_date_str(s, field):
    if not isinstance(s, str) or not DATE_RE.match(s):
        _verr(f"{field} must be a YYYY-MM-DD date")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        _verr(f"{field} must be a valid YYYY-MM-DD date")


def v_date(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    return parse_date_str(v, name)


def parse_dt_str(s, field):
    if not isinstance(s, str) or not s.strip():
        _verr(f"{field} must be an ISO 8601 UTC timestamp")
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _verr(f"{field} must be an ISO 8601 UTC timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def v_dt(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            _verr(f"{name} is required")
        return None
    return parse_dt_str(v, name)


def pagination():
    q = request.args
    raw_limit = q.get("limit")
    raw_offset = q.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        _verr("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        _verr("offset must be an integer")
    if limit < 1 or limit > 100:
        _verr("limit must be between 1 and 100")
    if offset < 0:
        _verr("offset must be >= 0")
    return limit, offset


def ts(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
