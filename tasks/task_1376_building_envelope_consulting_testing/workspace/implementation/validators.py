"""Request body / query validation helpers (validation tier 4)."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ERR_INVALID_REQUEST, raise_err

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """Parse the request JSON body exactly (Decimals for JSON floats).

    Missing body yields {}. A non-object or unparsable body is invalid.
    """
    raw = request.get_data()
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(value, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return value


def _invalid(msg):
    raise_err(ERR_INVALID_REQUEST, msg)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        _invalid(f"Field '{name}' is required and must be a string")
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        _invalid(f"Field '{name}' must be a string")
    return v


def _as_int(v, name):
    if isinstance(v, bool):
        _invalid(f"Field '{name}' must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, Decimal) and v == v.to_integral_value():
        return int(v)
    _invalid(f"Field '{name}' must be an integer")


def req_int(body, name, lo=None, hi=None):
    if name not in body:
        _invalid(f"Field '{name}' is required")
    v = _as_int(body.get(name), name)
    if lo is not None and v < lo:
        _invalid(f"Field '{name}' must be >= {lo}")
    if hi is not None and v > hi:
        _invalid(f"Field '{name}' must be <= {hi}")
    return v


def opt_int(body, name, default=None, lo=None, hi=None):
    if name not in body or body.get(name) is None:
        return default
    v = _as_int(body.get(name), name)
    if lo is not None and v < lo:
        _invalid(f"Field '{name}' must be >= {lo}")
    if hi is not None and v > hi:
        _invalid(f"Field '{name}' must be <= {hi}")
    return v


def req_num(body, name, lo=None, hi=None, lo_exclusive=False, hi_exclusive=False):
    if name not in body:
        _invalid(f"Field '{name}' is required")
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        _invalid(f"Field '{name}' must be a number")
    d = Decimal(v)
    if lo is not None:
        if lo_exclusive and not (d > lo):
            _invalid(f"Field '{name}' must be > {lo}")
        if not lo_exclusive and not (d >= lo):
            _invalid(f"Field '{name}' must be >= {lo}")
    if hi is not None:
        if hi_exclusive and not (d < hi):
            _invalid(f"Field '{name}' must be < {hi}")
        if not hi_exclusive and not (d <= hi):
            _invalid(f"Field '{name}' must be <= {hi}")
    return d


def opt_num(body, name, default=None, lo=None, hi=None):
    if name not in body or body.get(name) is None:
        return default
    return req_num(body, name, lo=lo, hi=hi)


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        _invalid(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_list(body, name):
    v = body.get(name)
    if not isinstance(v, list) or len(v) == 0:
        _invalid(f"Field '{name}' must be a non-empty array")
    return v


def req_date(body, name):
    v = req_str(body, name)
    return parse_date(v, name)


def parse_date(v, name):
    if not _DATE_RE.match(v):
        _invalid(f"Field '{name}' must be an ISO date (YYYY-MM-DD)")
    try:
        dt = datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _invalid(f"Field '{name}' must be a valid calendar date (YYYY-MM-DD)")
    if dt.strftime("%Y-%m-%d") != v:
        _invalid(f"Field '{name}' must be an ISO date (YYYY-MM-DD)")
    return dt.date()


def parse_iso8601_instant(v, name="to_iso8601"):
    if not isinstance(v, str):
        _invalid(f"Field '{name}' must be an ISO 8601 UTC instant")
    t = v.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _invalid(f"Field '{name}' must be an ISO 8601 UTC instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _invalid("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            _invalid("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _invalid("Query parameter 'offset' must be an integer")
        if offset < 0:
            _invalid("Query parameter 'offset' must be >= 0")
    return limit, offset
