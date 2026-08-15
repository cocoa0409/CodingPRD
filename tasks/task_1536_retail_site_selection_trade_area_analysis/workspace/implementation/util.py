"""Validation utilities, decimal arithmetic helpers, and date parsing."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import request

from errors import invalid_request
from response import ok_list

getcontext().prec = 80

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Decimal helpers — every rounding in the system is round-half-up.
# ---------------------------------------------------------------------------

def rhu(value, places):
    """Round-half-up a Decimal to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round-half-up to a whole integer and return a Python int."""
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------

def get_body(required=False):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = req_field(body, field)
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], str):
        raise invalid_request(f"Field {field} must be a string")
    return body[field]


def req_int(body, field, min_v=None, max_v=None):
    v = req_field(body, field)
    if not _is_int(v):
        raise invalid_request(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"Field {field} must be <= {max_v}")
    return v


def opt_int(body, field, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise invalid_request(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"Field {field} must be <= {max_v}")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        raise invalid_request(f"Field {field} must be a boolean")
    return body[field]


def req_enum(body, field, choices):
    v = req_field(body, field)
    if not isinstance(v, str) or v not in choices:
        raise invalid_request(
            f"Field {field} must be one of: {', '.join(choices)}")
    return v


def parse_date_str(s):
    """Strict YYYY-MM-DD parse; returns datetime.date or None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def req_date(body, field):
    v = req_field(body, field)
    d = parse_date_str(v)
    if d is None:
        raise invalid_request(f"Field {field} must be an ISO 8601 date (YYYY-MM-DD)")
    return v, d


def parse_datetime_str(s):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    v = req_field(body, field)
    dt = parse_datetime_str(v)
    if dt is None:
        raise invalid_request(f"Field {field} must be an ISO 8601 datetime")
    return v, dt


# ---------------------------------------------------------------------------
# Existence helpers for body-referenced foreign keys (layer 3, left-to-right).
# ---------------------------------------------------------------------------

def fk_exists(body, field, table, required=True):
    """Validate a body-referenced FK. Returns the referenced record.

    Missing/None -> 400 when required, None otherwise. Wrong type -> 400.
    Present but dangling -> 404.
    """
    from errors import not_found
    if field not in body or body[field] is None:
        if required:
            raise invalid_request(f"Missing required field: {field}")
        return None
    v = body[field]
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string id")
    rec = table.get(v)
    if rec is None:
        raise not_found(f"Referenced {field} does not exist: {v}")
    return rec


# ---------------------------------------------------------------------------
# Pagination + list rendering
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            raise invalid_request("Query parameter limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            raise invalid_request("Query parameter offset must be >= 0")
    return limit, offset


def list_response(records, serializer, filters=None):
    """records: iterable of internal dicts. Applies equality filters from the
    query string, sorts by created_at ascending (stable on insert order),
    paginates, and renders the array envelope."""
    items = list(records)
    if filters:
        for field in filters:
            raw = request.args.get(field)
            if raw is not None:
                items = [r for r in items if str(r.get(field)) == raw]
    items.sort(key=lambda r: (r["created_at_sort"], r["_seq"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
