"""Shared helpers: payload validation, datetime/date parsing, entity stamping,
pagination, and slot/time utilities per PRD 2.3-2.9."""

from datetime import datetime, date, time, timedelta, timezone

from flask import request

import errors
from db import new_id, iso_from_dt
import clock


# ---------------------------------------------------------------------------
# Body / field validation (priority 2: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_field(body, field):
    val = body.get(field)
    if val is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    return val


def require_str(body, field):
    val = require_field(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"{field} must be a non-empty string")
    return val


def optional_str(body, field, default=None):
    val = body.get(field)
    if val is None:
        return default
    if not isinstance(val, str):
        raise errors.invalid_request(f"{field} must be a string")
    return val


def require_bool(body, field):
    val = require_field(body, field)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"{field} must be a boolean")
    return val


def optional_bool(body, field, default=None):
    val = body.get(field)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise errors.invalid_request(f"{field} must be a boolean")
    return val


def _check_int(val, field):
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"{field} must be an integer")
    return val


def require_int(body, field, min_v=None, max_v=None):
    val = _check_int(require_field(body, field), field)
    if min_v is not None and val < min_v:
        raise errors.invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and val > max_v:
        raise errors.invalid_request(f"{field} must be <= {max_v}")
    return val


def optional_int(body, field, min_v=None, max_v=None, default=None):
    val = body.get(field)
    if val is None:
        return default
    val = _check_int(val, field)
    if min_v is not None and val < min_v:
        raise errors.invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and val > max_v:
        raise errors.invalid_request(f"{field} must be <= {max_v}")
    return val


def require_enum(body, field, allowed):
    val = require_field(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"{field} must be one of {sorted(allowed)}")
    return val


# ---------------------------------------------------------------------------
# Datetime / date parsing
# ---------------------------------------------------------------------------

def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_iso(body, field):
    return parse_iso(require_field(body, field), field)


def parse_date(value, field="date"):
    """Parse a YYYY-MM-DD calendar date string."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be a YYYY-MM-DD date string")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise errors.invalid_request(f"{field} is not a valid YYYY-MM-DD date")


def require_date(body, field):
    return parse_date(require_field(body, field), field)


def slot_datetime(d, minute):
    """Naive-local slot datetime, modeled as UTC for logical-clock comparisons."""
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc) + timedelta(minutes=minute)


# ---------------------------------------------------------------------------
# Entity stamping (PRD 2.5)
# ---------------------------------------------------------------------------

def logical_now_iso():
    return iso_from_dt(clock.now())


def new_entity(extra=None):
    """Common fields: id, created_at, updated_at, version. Also registers the
    entity's insertion sequence (side table; never serialized)."""
    from db import store
    now_iso = logical_now_iso()
    ent = {
        "id": new_id(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    if extra:
        ent.update(extra)
    store.seq_of[ent["id"]] = store.next_seq()
    return ent


def sort_key(ent):
    """Deterministic order: created_at ASC, then insertion (submission) order."""
    from db import store
    return (ent.get("created_at", ""), store.seq_of.get(ent.get("id"), 0))


def touch(ent):
    """Refresh updated_at + bump version on mutation."""
    ent["updated_at"] = logical_now_iso()
    ent["version"] = ent.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    """Sort by created_at ASC and apply limit/offset from query params."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    from response import success_list
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Slot arithmetic (PRD 2.9)
# ---------------------------------------------------------------------------

PRIME_START_MINUTE = 1020
LIGHTS_BUFFER_MINUTES = 30
BLOCK_MINUTES = 15
REFUND_AUTO_APPROVE_MAX_CENTS = 10000


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: adjacency (end == start) is NOT overlap."""
    return a_start < b_end and b_start < a_end


def prime_hours(start_minute, end_minute):
    """Whole hours of a slot when prime (start >= 1020), else 0."""
    if start_minute >= PRIME_START_MINUTE:
        return (end_minute - start_minute) // 60
    return 0


def week_monday(d):
    """Monday of the Monday-Sunday week containing date d."""
    return d - timedelta(days=d.weekday())


def ceil_div(a, b):
    return -(-a // b)
