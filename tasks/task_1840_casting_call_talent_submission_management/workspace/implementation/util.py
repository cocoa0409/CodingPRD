"""Shared helpers: logical clock, timestamps, serialization, validation, pagination."""
import uuid
from datetime import datetime, timezone, timedelta

from flask import request

import db
from errors import err_invalid_request

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4). Startup default is exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    return _logical_clock


def set_logical_clock(dt):
    global _logical_clock
    _logical_clock = dt


def iso(dt):
    """Serialize an aware UTC datetime as ISO 8601 with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


def parse_dt(value):
    """Parse an ISO-8601 datetime (accepts trailing Z, offsets, or date-only).
    Returns an aware UTC datetime, or None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Record construction / mutation
# ---------------------------------------------------------------------------

def new_record(fields):
    now = wall_now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.9)."""
    rec["updated_at"] = wall_now()
    rec["version"] += 1


def serialize(rec, extra=None):
    """Convert internal record to API JSON: datetimes to ISO, drop _internal keys."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Payload validation (PRD 2.8 step 8 -- deliberately LAST in the pipeline)
# ---------------------------------------------------------------------------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def get_payload():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def req_field(body, name):
    """Present-and-not-None check used inside final field validation."""
    return name in body and body[name] is not None


def check_string(body, name, required=True):
    if not req_field(body, name):
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str) or not v.strip():
        raise err_invalid_request(f"Field {name} must be a non-empty string")
    return v


def check_bool(body, name, required=True, default=None):
    if not req_field(body, name):
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field {name} must be a boolean")
    return v


def check_int(body, name, required=True, default=None, min_v=None, max_v=None):
    if not req_field(body, name):
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return default
    v = body[name]
    if not _is_int(v):
        raise err_invalid_request(f"Field {name} must be an integer")
    if min_v is not None and v < min_v:
        raise err_invalid_request(f"Field {name} below minimum {min_v}")
    if max_v is not None and v > max_v:
        raise err_invalid_request(f"Field {name} above maximum {max_v}")
    return v


def check_enum(body, name, allowed, required=True, default=None):
    if not req_field(body, name):
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return default
    v = body[name]
    if v not in allowed:
        raise err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def check_datetime(body, name, required=True):
    if not req_field(body, name):
        if required:
            raise err_invalid_request(f"Missing required field: {name}")
        return None
    dt = parse_dt(body[name])
    if dt is None:
        raise err_invalid_request(f"Field {name} must be an ISO 8601 datetime")
    return dt


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 (min 1, max 100), offset default 0.
# ---------------------------------------------------------------------------

def paginate(records):
    """records: full filtered iterable of internal records. Returns
    (page_records, limit, offset, total_count) sorted by created_at asc."""
    args = request.args
    try:
        limit = int(args.get("limit", "10"))
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", "0"))
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def filter_status(records):
    """Apply the common ?status= query filter when present."""
    status = request.args.get("status")
    if status is None:
        return list(records)
    return [r for r in records if r.get("status") == status]
