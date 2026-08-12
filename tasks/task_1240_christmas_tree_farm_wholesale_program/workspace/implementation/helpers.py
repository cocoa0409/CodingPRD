"""Request-body validation primitives, record factory, and pagination.

Validation pipeline (PRD 2.6 / SCAFFOLD 1.4): auth -> role/ownership -> SoD ->
existence (left-to-right) -> well-formedness -> state -> posture -> guards ->
temporal -> referential -> constraint -> fiscal. The primitives here implement
the existence and well-formedness layers; route code wires the ordering.
"""
import uuid

from flask import request

from db import store
from errors import malformed, not_found
from timeutil import fmt_dt


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------

def body():
    """The JSON request body as a dict. Absent body is treated as {} so that
    required-field checks produce ERR_MALFORMED_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise malformed("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def has_field(data, name):
    return name in data and data[name] is not None


def req_field(data, name):
    if not has_field(data, name):
        raise malformed("Missing required field: %s" % name)
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or not v:
        raise malformed("Field %s must be a non-empty string" % name)
    return v


def req_int(data, name, minimum=None):
    v = req_field(data, name)
    if not is_int(v):
        raise malformed("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise malformed("Field %s must be >= %d" % (name, minimum))
    return v


def req_num(data, name):
    v = req_field(data, name)
    if not is_num(v):
        raise malformed("Field %s must be a number" % name)
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise malformed("Field %s must be one of %s" % (name, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def new_record(fields):
    """Mint a resource with the PRD 2.5 common fields (id/created_at/
    updated_at/version). created_at/updated_at use the logical clock; _seq is
    the internal insertion order used as the created_at-ASC sort key."""
    ts = fmt_dt(store.clock)
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(store.seq),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD 2.5)."""
    rec["updated_at"] = fmt_dt(store.clock)
    rec["version"] += 1


def get_or_404(collection, rid, msg="Resource not found"):
    rec = collection.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise not_found(msg)
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise malformed("limit and offset must be integers")
    # Declared bounds: limit in [1, 100] (default 10), offset >= 0 (default 0).
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Window an already-sorted list; returns (page, pagination-meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
