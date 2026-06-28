"""Shared helpers: money rounding, request parsing, pagination, common fields."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import db, new_id, now_ts


# -----------------------------------------------------------------------------
# Money / rounding (PRD §2.5): products of cents x fraction round half-up.
# -----------------------------------------------------------------------------

def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half-up.

    `value` may be int, float, or Decimal. We route through Decimal(str(...)) so
    that float inputs (e.g. 575000 * 1.15) round on their decimal representation,
    matching the PRD's two-decimal-place dollar semantics."""
    d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -----------------------------------------------------------------------------
# Common system fields (PRD §2.4): id, created_at, updated_at, version.
# -----------------------------------------------------------------------------

def stamp_new(record):
    """Populate id/created_at/updated_at/version + internal seq on a fresh record."""
    ts = now_ts()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4/§2.6)."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 1) + 1
    return record


# -----------------------------------------------------------------------------
# Request body / field parsing
# -----------------------------------------------------------------------------

def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if no body)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def require_str(body, field):
    require_fields(body, [field])
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return val


def require_int(body, field, *, minimum=None, non_negative=False):
    require_fields(body, [field])
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if non_negative and val < 0:
        raise errors.invalid_request(f"Field {field} must be non-negative")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}")
    return val


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_number(body, field):
    """Require a numeric (int or float) field, returned as-is."""
    require_fields(body, [field])
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return val


# -----------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# -----------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def sort_and_paginate(records, limit, offset):
    """Sort by created_at ASC (seq tiebreak) and slice (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
