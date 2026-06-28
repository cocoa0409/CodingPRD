"""Shared helpers: body parsing, field validation, pagination, ownership."""
from flask import request

from db import store, new_id, now_iso_ms
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENCE_NOT_FOUND,
    ERR_FORBIDDEN,
)


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict, defaulting to {} for empty."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        # empty body or unparseable
        if request.data.strip() == b"":
            return {}
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


# --------------------------------------------------------------------------
# Field validation primitives (ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def opt_string(body, name, default=""):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def require_int(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    return v


def opt_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def require_enum(body, name, allowed):
    v = require_string(body, name)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def check_range(value, name, lo=None, hi=None, lo_inclusive=True, hi_inclusive=True):
    if lo is not None:
        if lo_inclusive and value < lo:
            raise err(ERR_INVALID_REQUEST, "Field %s below minimum" % name)
        if not lo_inclusive and value <= lo:
            raise err(ERR_INVALID_REQUEST, "Field %s below minimum" % name)
    if hi is not None:
        if hi_inclusive and value > hi:
            raise err(ERR_INVALID_REQUEST, "Field %s above maximum" % name)
        if not hi_inclusive and value >= hi:
            raise err(ERR_INVALID_REQUEST, "Field %s above maximum" % name)
    return value


# --------------------------------------------------------------------------
# Pagination (SCAFFOLD §1.0: limit default 10, min 1, max 100; offset default 0)
# --------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_int_param("limit", 10)
    offset = _parse_int_param("offset", 0)
    if limit < 1:
        raise err(ERR_INVALID_REQUEST, "limit must be >= 1")
    if limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be <= 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Query param %s must be an integer" % name)


def paginate(rows, limit, offset):
    """Sort by created_at asc, then slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND for path params)
# --------------------------------------------------------------------------
def get_or_404(collection, rid):
    row = collection.get(rid)
    if row is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return row


def ref_or_422(collection, rid):
    """FK body reference lookup."""
    row = collection.get(rid)
    if row is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced resource not found: %s" % rid)
    return row


# --------------------------------------------------------------------------
# System-managed common fields
# --------------------------------------------------------------------------
def make_entity(initial_version=1, has_version=True):
    ts = now_iso_ms()
    row = {
        "id": new_id(),
        "created_at": ts,
    }
    if has_version:
        row["updated_at"] = ts
        row["version"] = initial_version
    return row


def touch(row):
    """Mark a versioned entity mutated: bump version + updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now_iso_ms()
