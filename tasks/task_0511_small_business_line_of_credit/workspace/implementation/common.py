"""Common helpers: timestamps, system fields, request parsing, pagination, sorting.

System fields (PRD §2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO 8601 UTC timestamp with three fractional digits
  - updated_at: ISO 8601 UTC, most recent modification
  - version: integer starting at 1, +1 on every mutation
LedgerEntry is the exception: only id + created_at (no updated_at, no version).

All these time fields are stamped from the LOGICAL clock (PRD §2.4: "Every 'now'
referenced in this specification" is evaluated against the logical clock).
"""
from datetime import datetime, timezone

from flask import request

import db
from clock import clock
from errors import err, ERR_INVALID_REQUEST


def iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return clock.now()


def stamp_create(record):
    """Stamp id/created_at/updated_at/version + internal seq."""
    record["id"] = db.new_id()
    ts = iso_millis(now())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    # store the logical-clock datetime for precise comparisons
    record["_created_dt"] = now()
    record["_updated_dt"] = now()
    return record


def stamp_create_ledger(record):
    """LedgerEntry: only id + created_at (immutable, no version/updated_at)."""
    record["id"] = db.new_id()
    record["created_at"] = iso_millis(now())
    record["_seq"] = db.next_seq()
    record["_created_dt"] = now()
    return record


def touch(record):
    """Mark a mutation: refresh updated_at, increment version."""
    record["updated_at"] = iso_millis(now())
    record["_updated_dt"] = now()
    record["version"] = record.get("version", 1) + 1


def parse_body():
    """Parse JSON body, tolerating empty/absent bodies as {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_datetime(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime, or None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(body, fields):
    """Ensure each named field is present (not None). Raises ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_int(body, field, *, minimum=None, exclusive_min=None):
    """Validate an integer field with optional bounds. Returns the int value."""
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    if exclusive_min is not None and val <= exclusive_min:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be > {exclusive_min}")
    return val


# ---- pagination & listing (PRD §2.3) ----
def parse_pagination():
    """Parse limit/offset query params. limit default 10, min 1, max 100;
    offset default 0, min 0. Invalid values -> ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sort_by_created(records):
    """Sort by created_at ASC; tie-break by internal creation seq (never id)."""
    return sorted(records, key=lambda r: (r["_seq"],))


def paginate(records, limit, offset):
    """Return (page_items, total_count)."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, total


def list_response(records, serializer):
    """Sort by created_at ASC, paginate, serialize, and build an array response."""
    from response import array_response
    limit, offset = parse_pagination()
    ordered = sort_by_created(records)
    page, total = paginate(ordered, limit, offset)
    items = [serializer(r) for r in page]
    return array_response(items, limit, offset, total)
