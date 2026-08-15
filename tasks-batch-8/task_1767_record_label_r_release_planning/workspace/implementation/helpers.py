"""Shared helpers: body parsing, field validation, dates, pagination, entity CRUD glue."""

import calendar
import re
from datetime import date, timedelta

from flask import request

from db import db, new_id, now_iso
from errors import raise_err

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------

def get_body():
    """Parse the JSON request body. Empty body -> {}. Non-object -> 400."""
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------

def _fail(name):
    raise_err("ERR_INVALID_REQUEST", "Invalid or missing field: %s" % name)


def req_present(body, name):
    if name not in body or body[name] is None:
        _fail(name)
    return body[name]


def v_str(body, name, required=True, allow_null=False):
    if name not in body:
        if required:
            _fail(name)
        return None
    val = body[name]
    if val is None:
        if allow_null or not required:
            return None
        _fail(name)
    if not isinstance(val, str):
        _fail(name)
    return val


def v_int(body, name, required=True, min_v=None, max_v=None, choices=None):
    if name not in body or body[name] is None:
        if required:
            _fail(name)
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        _fail(name)
    if min_v is not None and val < min_v:
        _fail(name)
    if max_v is not None and val > max_v:
        _fail(name)
    if choices is not None and val not in choices:
        _fail(name)
    return val


def v_num(body, name, required=True, min_v=None, max_v=None):
    if name not in body or body[name] is None:
        if required:
            _fail(name)
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _fail(name)
    if min_v is not None and val < min_v:
        _fail(name)
    if max_v is not None and val > max_v:
        _fail(name)
    return val


def v_bool(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _fail(name)
        return None
    if not isinstance(body[name], bool):
        _fail(name)
    return body[name]


def v_enum(body, name, allowed, required=True):
    val = v_str(body, name, required=required)
    if val is None:
        return None
    if val not in allowed:
        _fail(name)
    return val


def v_date(body, name, required=True):
    val = v_str(body, name, required=required)
    if val is None:
        return None
    if parse_date(val) is None:
        _fail(name)
    return val


def v_period(body, name, required=True):
    val = v_str(body, name, required=required)
    if val is None:
        return None
    if not PERIOD_RE.match(val):
        _fail(name)
    return val


def v_str_list(body, name, required=True, non_empty=False):
    if name not in body or body[name] is None:
        if required:
            _fail(name)
        return None
    val = body[name]
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        _fail(name)
    if non_empty and len(val) == 0:
        _fail(name)
    return val


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

def parse_date(s):
    """Strict YYYY-MM-DD parse; returns datetime.date or None."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        return date(y, m, d)
    except ValueError:
        return None


def add_months(d, months):
    """Calendar-month addition with day clamping."""
    total = (d.year * 12 + (d.month - 1)) + months
    y, m0 = divmod(total, 12)
    m = m0 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap years
        return d.replace(year=d.year + years, day=28)


def days_later(d, n):
    return d + timedelta(days=n)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def make_entity(fields):
    """Create an entity dict with common system fields."""
    ent = dict(fields)
    ent["id"] = new_id()
    ts = now_iso()
    ent["created_at"] = ts
    ent["updated_at"] = ts
    ent["version"] = 1
    ent["_seq"] = db.next_seq()
    return ent


def touch(ent):
    """Refresh updated_at and bump version (skipped for append-only reports)."""
    ent["updated_at"] = now_iso()
    ent["version"] = ent.get("version", 1) + 1


def serialize(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise_err("ERR_NOT_FOUND", "Resource not found: %s" % entity_id)
    return ent


# ---------------------------------------------------------------------------
# Pagination & listing
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
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_page(items):
    """Sort by (created_at, insertion seq) ascending and paginate."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return [serialize(e) for e in page], pagination


def apply_filters(items, filters):
    """filters: list of (query_param, accessor) with string equality semantics."""
    out = list(items)
    for param, accessor in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        out = [e for e in out if accessor(e) == raw]
    return out


def bool_filter(items, param, accessor):
    raw = request.args.get(param)
    if raw is None:
        return list(items)
    low = raw.lower()
    if low == "true":
        want = True
    elif low == "false":
        want = False
    else:
        raise_err("ERR_INVALID_REQUEST", "%s must be true or false" % param)
    return [e for e in items if accessor(e) == want]
