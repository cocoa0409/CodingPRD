"""Common field management, numeric precision helpers, datetime parsing, pagination."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

import errors
from db import store, new_id


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    """Set id, created_at, (updated_at, version) on a freshly created record.
    StockingEvent / FeedLog / WaterQualityReading carry only id + created_at
    (with_version=False)."""
    now = store.now_iso()
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = store.next_seq()  # internal stable sort key, stripped on output
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version by exactly 1 (PRD §2.4)."""
    record["updated_at"] = store.now_iso()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Numeric precision (PRD §2.6) — 2 dp, round half up
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def round2(x):
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Field validation helpers — bad field -> ERR_INVALID_REQUEST (400)
# ---------------------------------------------------------------------------
def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            raise errors.invalid_request("Request body is not valid JSON.")
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_str(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string.")
    return val


def require_number(body, field, gt=None, ge=None, le=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    _check_bounds(field, val, gt, ge, le)
    return val


def optional_number(body, field, default=None, gt=None, ge=None, le=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    _check_bounds(field, val, gt, ge, le)
    return val


def require_int(body, field, gt=None, ge=None, le=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    _check_bounds(field, val, gt, ge, le)
    return val


def optional_int(body, field, default=None, gt=None, ge=None, le=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    _check_bounds(field, val, gt, ge, le)
    return val


def _check_bounds(field, val, gt, ge, le):
    if gt is not None and not (val > gt):
        raise errors.invalid_request(f"Field '{field}' must be greater than {gt}.")
    if ge is not None and not (val >= ge):
        raise errors.invalid_request(f"Field '{field}' must be at least {ge}.")
    if le is not None and not (val <= le):
        raise errors.invalid_request(f"Field '{field}' must be at most {le}.")


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def parse_iso(raw):
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(body, field):
    """Parse a required ISO 8601 datetime field into aware UTC datetime."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    raw = body[field]
    if not isinstance(raw, str):
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 string.")
    dt = parse_iso(raw)
    if dt is None:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 datetime.")
    return dt


def to_iso(dt):
    """Render an aware UTC datetime to ISO 8601 with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


def days_between(later, earlier):
    """Whole days elapsed, fractional day discarded (floor)."""
    delta = later - earlier
    total = delta.total_seconds() / 86400.0
    import math
    return int(math.floor(total))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — out-of-range -> ERR_VALIDATION_LIMIT_RANGE (400)
# ---------------------------------------------------------------------------
def get_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit_range("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation_limit_range("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit_range("offset must be an integer.")
        if offset < 0:
            raise errors.validation_limit_range("offset must be at least 0.")

    return limit, offset


def paginate(records):
    """Sort by created_at ASC (PRD §2.3), apply limit/offset window."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, limit, offset, total


# ---------------------------------------------------------------------------
# Existence helpers (PRD §2.5)
# ---------------------------------------------------------------------------
def must_get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise errors.not_found()
    return rec


def require_fk(body, field, collection):
    """Resolve a body foreign key. PRD §2.5: existence (404) precedes business
    rules. A missing/non-string FK cannot be looked up -> ERR_INVALID_REQUEST."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string.")
    rec = collection.get(val)
    if rec is None:
        raise errors.not_found()
    return val, rec


def optional_fk(body, field, collection):
    """Optional body FK; present-but-unresolvable -> 404; absent/null -> (None, None)."""
    if field not in body or body[field] is None:
        return None, None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string.")
    rec = collection.get(val)
    if rec is None:
        raise errors.not_found()
    return val, rec
