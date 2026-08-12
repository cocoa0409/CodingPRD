"""Field-shape validators (priority-16 ERR_INVALID_REQUEST) and pagination."""
import re
from datetime import date

from flask import request

import errors

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def json_body():
    """Return the parsed JSON object body; {} when absent. 400 on non-object JSON."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise errors.invalid_request(f"Field '{field}' must be a string")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    if min_v is not None and v < min_v:
        raise errors.invalid_request(f"Field '{field}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise errors.invalid_request(f"Field '{field}' must be <= {max_v}")
    return v


def req_number(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number")
    if min_v is not None and v < min_v:
        raise errors.invalid_request(f"Field '{field}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise errors.invalid_request(f"Field '{field}' must be <= {max_v}")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_date(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise errors.invalid_request(f"Field '{field}' must be a YYYY-MM-DD date")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise errors.invalid_request(f"Field '{field}' must be a valid calendar date")
    return v


def opt_bool(body, field, default):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean")
    return v


def req_hhmm(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not _TIME_RE.match(v):
        raise errors.invalid_request(f"Field '{field}' must be an HH:MM 24h time")
    return v


def opt_int_field(body, field):
    """Optional integer OCC field: returns None when absent; 400 when malformed."""
    if field not in body:
        return None
    v = body.get(field)
    if not _is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    return v


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise errors.invalid_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise errors.invalid_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise errors.invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(items):
    """Slice items per pagination params; returns (page, pagination-meta)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def apply_filters(items, mapping):
    """mapping: {query_param: (accessor, kind)} kind in ('str','int','bool')."""
    for param, (accessor, kind) in mapping.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            if raw.lower() == "true":
                val = True
            elif raw.lower() == "false":
                val = False
            else:
                continue
        elif kind == "int":
            try:
                val = int(raw, 10)
            except ValueError:
                continue
        else:
            val = raw
        items = [e for e in items if accessor(e) == val]
    return items
