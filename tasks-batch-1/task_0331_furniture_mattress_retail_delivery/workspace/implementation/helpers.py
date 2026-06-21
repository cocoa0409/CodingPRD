"""Shared request-handling helpers: body parsing, type/range validation,
common-field stamping, pagination, and entity-fetch with existence checks.
"""
from flask import request

import clock
import db
from errors import err


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON body. Missing/empty body -> {}. Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field validation (ERR_INVALID_REQUEST, 422)
# ---------------------------------------------------------------------------
def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def _is_int(v):
    # bool is a subclass of int; exclude it for integer fields.
    return isinstance(v, int) and not isinstance(v, bool)


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = require(body, field)
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    _check_range(field, v, minimum, maximum)
    return v


def optional_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    _check_range(field, v, minimum, maximum)
    return v


def _check_range(field, v, minimum, maximum):
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (field, maximum))


def require_bool(body, field):
    v = require(body, field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    """Set id, created_at, updated_at, version (version only when with_version)."""
    ts = clock.iso_now()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version (a mutation, PRD §2.4 / §2.8)."""
    record["updated_at"] = clock.iso_now()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Existence (ERR_NOT_FOUND, 404)
# ---------------------------------------------------------------------------
def fetch(store, resource_id):
    rec = store.get(resource_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % resource_id)
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    """Read limit/offset query params. Defaults limit=10 (min 1, max 100), offset=0.
    Invalid values are rejected with ERR_INVALID_REQUEST.
    """
    limit = _parse_query_int("limit", 10)
    offset = _parse_query_int("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer." % name)


def paginate(rows, limit, offset):
    """Sort by created_at asc (stable via _seq), then window."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
