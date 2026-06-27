"""Common field management, numeric precision helpers, datetime parsing,
pagination, and existence helpers."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import store, new_id


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    """Set id, created_at, (updated_at, version) on a freshly created record.
    Inspection and Feeding are immutable append-only events: id + created_at only
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
    """Refresh updated_at and bump version by exactly 1 (PRD §2.6)."""
    record["updated_at"] = store.now_iso()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Numeric precision (PRD §2.10)
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def round2(x):
    """2 dp, round half up — weight yields."""
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_cents(x):
    """Reduce a fractional-cents value to an integer with round-half-up."""
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Datetime parsing
# ---------------------------------------------------------------------------
def parse_iso(raw):
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if s == "":
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(body, field):
    """Parse a required ISO 8601 datetime field into an aware UTC datetime."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    raw = body[field]
    if not isinstance(raw, str):
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 string.")
    dt = parse_iso(raw)
    if dt is None:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 datetime.")
    return dt


def iso_from_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Field validation helpers
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


def require_number(body, field, non_negative=False, positive=False):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    if positive and val <= 0:
        raise errors.validation(f"Field '{field}' must be positive.")
    if non_negative and val < 0:
        raise errors.validation(f"Field '{field}' must be non-negative.")
    return val


def optional_number(body, field, default=None, non_negative=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{field}' must be a number.")
    if non_negative and val < 0:
        raise errors.validation(f"Field '{field}' must be non-negative.")
    return val


def require_int(body, field, non_negative=False, minimum=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if non_negative and val < 0:
        raise errors.validation(f"Field '{field}' must be non-negative.")
    if minimum is not None and val < minimum:
        raise errors.validation(f"Field '{field}' must be at least {minimum}.")
    return val


def optional_int(body, field, default=0, non_negative=False, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if non_negative and val < 0:
        raise errors.validation(f"Field '{field}' must be non-negative.")
    if minimum is not None and val < minimum:
        raise errors.validation(f"Field '{field}' must be at least {minimum}.")
    return val


def require_bool(body, field):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean.")
    return val


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
# Pagination (PRD §2.3)
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
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be at least 0.")

    return limit, offset


def paginate(records):
    """Sort by created_at ASC (PRD §2.3), apply limit/offset window."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, limit, offset, total


# ---------------------------------------------------------------------------
# Existence helpers (PRD §2.7)
# ---------------------------------------------------------------------------
def must_get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise errors.not_found()
    return rec


def require_fk(body, field, collection):
    """Resolve a body foreign key. PRD §2.7: a present FK string that does not
    resolve is ERR_FK_NOT_FOUND. A missing/non-string FK is ERR_INVALID_REQUEST."""
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string.")
    rec = collection.get(val)
    if rec is None:
        raise errors.fk_not_found()
    return val, rec


def optional_fk(body, field, collection):
    """Resolve an optional body foreign key; null is allowed (returns None)."""
    if field not in body or body[field] is None:
        return None, None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{field}' must be a non-empty string.")
    rec = collection.get(val)
    if rec is None:
        raise errors.fk_not_found()
    return val, rec
