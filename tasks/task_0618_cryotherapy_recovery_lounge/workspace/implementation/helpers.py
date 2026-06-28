"""Shared request-parsing, validation, pagination, mutation, and money helpers."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import db, new_id, now_ts


# ---------------------------------------------------------------------------
# Body parsing & field validation (ERR_INVALID_REQUEST = 400)
# ---------------------------------------------------------------------------

def get_body():
    """Return the parsed JSON body as a dict. Missing body -> {}. Malformed -> 400."""
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not (request.data or b""):
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: " + name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field must be a non-empty string: " + name)
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request("Field must be a string: " + name)
    return val


def require_bool(body, name):
    val = require_field(body, name)
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field must be a boolean: " + name)
    return val


def require_int(body, name):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def opt_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field must be an integer: " + name)
    return val


def require_int_min(body, name, minimum):
    val = require_int(body, name)
    if val < minimum:
        raise errors.invalid_request(
            "Field %s must be >= %d" % (name, minimum))
    return val


def opt_int_min(body, name, default, minimum):
    val = opt_int(body, name, default)
    if val is not None and val < minimum:
        raise errors.invalid_request(
            "Field %s must be >= %d" % (name, minimum))
    return val


def require_enum(body, name, allowed):
    val = require_str(body, name)
    if val not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of %s" % (name, sorted(allowed)))
    return val


def require_object(body, name):
    val = require_field(body, name)
    if not isinstance(val, dict):
        raise errors.invalid_request("Field must be an object: " + name)
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, in [1,100]; offset default 0, >= 0.
# Out-of-range -> ERR_VALIDATION_PAGINATION (400).
# ---------------------------------------------------------------------------

def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.pagination("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.pagination("limit must be in [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.pagination("offset must be an integer")
        if offset < 0:
            raise errors.pagination("offset must be >= 0")
    return limit, offset


def sort_by_created(items):
    """Sort by creation order ascending (PRD §2.3 default sort).

    Records carry a monotonic '_seq' assigned at creation, so ordering is stable
    and clock-independent even when created_at timestamps collide under a frozen
    logical clock.
    """
    return sorted(items, key=lambda r: r["_seq"])


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.5): integer cents, round half up.
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round half up to an integer."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


# ---------------------------------------------------------------------------
# Common-field mutation (PRD §2.4, §2.6).
# ---------------------------------------------------------------------------

def stamp_new(record, with_version=True):
    """Stamp a freshly-created record with common fields from the logical clock."""
    ts = now_ts()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """A mutation of a resource: refresh updated_at and increment version
    (PRD §2.4, §2.6). Invoices are append-only and never touched."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 1) + 1
    return record
