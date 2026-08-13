"""Request-shape validation helpers. All failures raise ERR_VALIDATION (400)
unless otherwise noted (PRD section 2.9 gate 5)."""

import math
from datetime import date, datetime, timezone

from flask import request

import db
from errors import validation


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def _is_num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return False
    return True


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise validation(f"Field '{name}' is required and must be a string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise validation(f"Field '{name}' must be a string")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise validation(f"Field '{name}' is required and must be a boolean")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise validation(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise validation(f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_number(body, name, gt=None, ge=None):
    v = body.get(name)
    if not _is_num(v):
        raise validation(f"Field '{name}' is required and must be a number")
    if gt is not None and not v > gt:
        raise validation(f"Field '{name}' must be greater than {gt}")
    if ge is not None and not v >= ge:
        raise validation(f"Field '{name}' must be at least {ge}")
    return v


def req_int(body, name, gt=None, ge=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise validation(f"Field '{name}' is required and must be an integer")
    if gt is not None and not v > gt:
        raise validation(f"Field '{name}' must be greater than {gt}")
    if ge is not None and not v >= ge:
        raise validation(f"Field '{name}' must be at least {ge}")
    return v


def parse_date_str(v, name):
    if not isinstance(v, str):
        raise validation(f"Field '{name}' must be a YYYY-MM-DD date string")
    try:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError
        return date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except (ValueError, IndexError):
        raise validation(f"Field '{name}' must be a valid YYYY-MM-DD date")


def req_date(body, name):
    return parse_date_str(body.get(name), name)


def parse_datetime_str(v, name):
    if not isinstance(v, str):
        raise validation(f"Field '{name}' must be an ISO 8601 datetime string")
    s = v.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise validation(f"Field '{name}' must be a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, name):
    return parse_datetime_str(body.get(name), name)


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise validation("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise validation("Query parameter 'offset' must be at least 0")
    return limit, offset


def page(items, limit, offset):
    """Sort by created_at ascending (insertion order tiebreak) and paginate."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    return [db.pub(r) for r in ordered[offset:offset + limit]], total
