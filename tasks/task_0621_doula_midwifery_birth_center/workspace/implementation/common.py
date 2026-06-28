"""Shared helpers: timestamps, versioning, pagination, datetime parsing,
request-body field validation."""
from datetime import datetime, timezone
from flask import request

from db import db, new_id, iso_now
from errors import err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Common server-managed fields (§2.4)
# ---------------------------------------------------------------------------
def stamp_new(record, versioned=True):
    """Attach id/created_at/updated_at/version to a brand-new record.

    created_at/updated_at are server-minted wall-clock ISO 8601 UTC values
    with three fractional digits. A monotonic sequence pins ascending sort
    order so list endpoints are deterministic even within the same millisecond.
    """
    now = iso_now(datetime.now(timezone.utc))
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version by one (§2.4)."""
    record["updated_at"] = iso_now(datetime.now(timezone.utc))
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serialization — strip internal-only keys (those prefixed with "_")
# ---------------------------------------------------------------------------
def public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Pagination (§2.3): limit default 10 (min 1, max 100), offset default 0.
# ---------------------------------------------------------------------------
def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (tie-broken by monotonic seq) and slice."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Request body parsing / field validation (§2.6 priority 4)
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_string(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "%s must be a string" % field)
    return v


def require_int(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "%s must be >= %s" % (field, minimum))
    return v


def require_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    v = body[field]
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "%s must be one of %s" % (field, sorted(allowed)))
    return v


def require_datetime(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
    parse_dt(v, field)  # validate parseability; stored as the original string
    return v


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 string to an aware UTC datetime for comparison."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
