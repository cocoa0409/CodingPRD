"""Common-field machinery, body parsing, validation primitives, pagination."""
from flask import request

from db import db, new_id, now_iso_millis, clock_now
from errors import err


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------

def stamp_common(record):
    """Attach id/created_at/updated_at/version to a fresh record."""
    ts = now_iso_millis()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bump: version += 1 and updated_at refreshed (PRD §2.8)."""
    record["version"] += 1
    record["updated_at"] = now_iso_millis()


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------

def get_json_body():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.data is None or request.data == b"":
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "malformed JSON body")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
        return body
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "field %s must be a non-empty string" % name)
    return val


def optional_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "field %s must be a string" % name)
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return val


def optional_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "field %s must be an integer" % name)
    return val


def require_number(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return val


def optional_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "field %s must be a number" % name)
    return val


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "field %s must be a boolean" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (name, sorted(allowed)))
    return val


def optional_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_INVALID_REQUEST", "field %s must be one of %s" % (name, sorted(allowed)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def get_pagination():
    """Parse limit/offset query params. limit default 10, min 1, max 100;
    offset default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_by_creation(records):
    """Sort by creation order ascending (PRD §2.3)."""
    return sorted(records, key=lambda r: r["_seq"])


def paginate(records, limit, offset):
    ordered = sort_by_creation(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Existence lookups (PRD §2.5)
# ---------------------------------------------------------------------------

def get_or_404(collection, _id, label="resource"):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return rec
