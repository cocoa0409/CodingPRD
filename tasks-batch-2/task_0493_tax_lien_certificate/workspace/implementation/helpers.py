"""Record construction, serialization, pagination, and request-body helpers.

Common fields (PRD §2.5): every entity carries id (UUID, no prefix), created_at
(ISO 8601 UTC, 3 fractional digits), updated_at (same format, refreshed on every
mutation), and integer version (starts at 1, +1 on every mutation).

Internal bookkeeping keys are stored alongside public fields but stripped before
serialization:
  _seq        creation sequence (stable list ordering)
  *_dt        aware-datetime mirrors of datetime string fields (for accrual math)
"""
from flask import request

import clock
import db
from errors import ERR_INVALID_REQUEST, ERR_VALIDATION, fail


def _now_iso():
    """Wall-clock creation/update timestamp (PRD §2.5), NOT the logical clock."""
    import response
    return response._timestamp()


def new_record(fields, versioned=True):
    """Build a record dict with common fields populated."""
    ts = _now_iso()
    rec = dict(fields)
    rec["id"] = db.new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Mark a record mutated: bump version and refresh updated_at (PRD §2.5/§2.8)."""
    rec["version"] += 1
    rec["updated_at"] = _now_iso()


# Keys that are internal bookkeeping and never serialized.
def _is_internal(key):
    return key == "_seq" or key.endswith("_dt")


def serialize(rec):
    """Public view of a record: drop internal keys."""
    return {k: v for k, v in rec.items() if not _is_internal(k)}


def get_body():
    """Parse the JSON request body. A missing/invalid body is an empty dict."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, names):
    """ERR_INVALID_REQUEST if any required field is missing or null."""
    for name in names:
        if name not in body or body[name] is None:
            fail(ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def as_int(value, name, error=ERR_INVALID_REQUEST):
    """Coerce a JSON value to int. bool is rejected; non-integers rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        fail(error, "Field %s must be an integer" % name)
    return value


def require_int(body, name, minimum=None, error_missing=ERR_INVALID_REQUEST,
                error_range=ERR_VALIDATION):
    """Require an integer field; optionally enforce a lower bound."""
    if name not in body or body[name] is None:
        fail(error_missing, "Missing required field: %s" % name)
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        fail(error_missing, "Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        fail(error_range, "Field %s must be >= %s" % (name, minimum))
    return val


def require_str(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        fail(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return val


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        fail(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return val


def paginate(items):
    """Apply limit/offset query params (PRD §2.3) to an already-sorted list.

    limit default 10, min 1, max 100; offset default 0, min 0. Returns
    (page_items, pagination_meta).
    """
    limit = _read_pagination_param("limit", default=10, minimum=1, maximum=100)
    offset = _read_pagination_param("offset", default=0, minimum=0, maximum=None)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def _read_pagination_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        fail(ERR_INVALID_REQUEST, "Pagination parameter %s must be an integer" % name)
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def sort_by_created(records):
    """Default list order (PRD §2.3): creation order ascending (by _seq)."""
    return sorted(records, key=lambda r: r["_seq"])
