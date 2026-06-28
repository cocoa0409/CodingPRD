"""Shared request parsing, validation, pagination, and serialization helpers."""
from datetime import datetime, timezone

from flask import request

import db
import errors
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict; {} when absent/empty.

    A body that is present but not valid JSON, or not an object, is malformed.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(errors.ERR_VALIDATION, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % n)


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err(errors.ERR_VALIDATION, "Field %s must be a non-empty string" % name)
    return v


def as_int(body, name, required=True, default=None, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
        return default
    v = body[name]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_VALIDATION, "Field %s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err(errors.ERR_VALIDATION, "Field %s must be >= %s" % (name, min_value))
    if max_value is not None and v > max_value:
        raise err(errors.ERR_VALIDATION, "Field %s must be <= %s" % (name, max_value))
    return v


def as_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(errors.ERR_VALIDATION, "Field %s must be a boolean" % name)
    return v


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(errors.ERR_VALIDATION,
                  "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def parse_datetime(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(errors.ERR_VALIDATION, "Missing required field: %s" % name)
        return default
    v = body[name]
    return _parse_iso(v, name)


def _parse_iso(v, name):
    if not isinstance(v, str):
        raise err(errors.ERR_VALIDATION, "Field %s must be an ISO-8601 string" % name)
    s = v.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise err(errors.ERR_VALIDATION, "Field %s is not a valid ISO-8601 datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def iso_from_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- Pagination (PRD §2.3) ----

def parse_pagination():
    """Return (limit, offset). limit default 10 (min 1, max 100); offset
    default 0 (min 0). Out-of-bounds -> ERR_VALIDATION."""
    limit = _parse_query_int("limit", default=10, min_value=1, max_value=100)
    offset = _parse_query_int("offset", default=0, min_value=0, max_value=None)
    return limit, offset


def _parse_query_int(name, default, min_value, max_value):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err(errors.ERR_VALIDATION, "Query param %s must be an integer" % name)
    if str(v) != raw.strip() and not (raw.strip().lstrip("+-").isdigit()):
        raise err(errors.ERR_VALIDATION, "Query param %s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err(errors.ERR_VALIDATION, "Query param %s must be >= %s" % (name, min_value))
    if max_value is not None and v > max_value:
        raise err(errors.ERR_VALIDATION, "Query param %s must be <= %s" % (name, max_value))
    return v


def sort_and_page(rows, limit, offset):
    """Sort by creation order (created_at ASC, tie-broken by seq) and slice."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
