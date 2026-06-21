"""Shared helpers: body parsing, type/enum/range validation, date parsing,
common system fields, and entity lookup. Validation precedence per PRD §2.5."""
from datetime import datetime, timezone, date

from flask import request

import db
from errors import err


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Return the parsed JSON body as a dict. A non-object / unparseable body is
    ERR_INVALID_REQUEST (PRD §2.5)."""
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if data is None:
            # empty body permitted for action endpoints with no input
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def as_str(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be a string")
    return v


def as_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be a boolean")
    return v


def as_int(body, key, required=True, default=None, min_val=None, max_val=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    # bool is a subclass of int — reject it as an integer value
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be an integer")
    if min_val is not None and v < min_val:
        raise err("ERR_INVALID_REQUEST", f"Field {key} below minimum {min_val}")
    if max_val is not None and v > max_val:
        raise err("ERR_INVALID_REQUEST", f"Field {key} above maximum {max_val}")
    return v


def as_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {key} not a legal value")
    return v


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------
def parse_datetime(body, key, required=True, default=None):
    """Parse an ISO 8601 date or datetime into a timezone-aware UTC datetime."""
    if key not in body or body[key] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {key}")
        return default
    v = body[key]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {key} must be an ISO date string")
    return parse_iso(v, key)


def parse_iso(v, key="value"):
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        # date-only string
        if len(v.strip()) == 10 and "T" not in v:
            d = date.fromisoformat(v.strip())
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {key} is not a valid ISO 8601 value")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def iso_out(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def days_in_month(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    cur = date(year, month, 1)
    return (nxt - cur).days


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------
def base_fields(with_version=True):
    f = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
    }
    if with_version:
        f["version"] = 1
    return f


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.4 / §2.6)."""
    entity["updated_at"] = db.now_iso()
    if "version" in entity:
        entity["version"] = entity["version"] + 1


# ---------------------------------------------------------------------------
# Existence lookups (PRD §2.5 — left-to-right; path id first)
# ---------------------------------------------------------------------------
def find_or_404(store, _id):
    ent = store.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    """limit default 10, min 1, max 100; offset default 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) then slice."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
