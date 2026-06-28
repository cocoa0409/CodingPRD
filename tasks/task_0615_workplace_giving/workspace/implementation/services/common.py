"""Common entity lifecycle helpers: creation stamps, mutation tracking,
serialization, request-body validation, pagination."""
import math
import re
from decimal import Decimal, ROUND_FLOOR

from flask import request

from db import db
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

EIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")

# Fields that are part of the common envelope (PRD §2.4) but are stored on each
# record; everything else in the record dict is a domain field.
COMMON_SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")


def stamp_create(record):
    """Assign id + created_at/updated_at + version=1 (PRD §2.4).

    Also assigns a hidden monotonic `_seq` used purely as a deterministic
    tiebreaker for "ascending created_at" ordering (PRD §2.3, §3.8) when the
    frozen logical clock makes two created_at strings identical. `_seq` is
    stripped by serialize() and never appears in any response.
    """
    now = db.clock.now_iso_ms()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation: refresh updated_at, bump version by 1 (PRD §2.4)."""
    record["updated_at"] = db.clock.now_iso_ms()
    record["version"] = record.get("version", 1) + 1


def serialize(record):
    """Return a JSON-safe copy of the stored record.

    Internal underscore-prefixed bookkeeping fields (e.g. `_seq`) are stripped
    so they never appear in any API response.
    """
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Request body parsing / field validation (priority 5: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be strictly greater than zero")
    return v


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_ein(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not EIN_RE.match(v):
        raise err(ERR_INVALID_REQUEST, "EIN must match the format NN-NNNNNNN")
    return v


def require_datetime(body, field):
    from db import parse_iso
    v = body.get(field)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime string")
    try:
        parse_iso(v)
    except Exception:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a valid ISO 8601 datetime")
    return v


# ---------------------------------------------------------------------------
# Existence (priority 4: ERR_NOT_FOUND), left-to-right
# ---------------------------------------------------------------------------
def find_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Referenced resource id does not exist")
    return rec


# ---------------------------------------------------------------------------
# Floor arithmetic (PRD §2.5): floor on every rate multiplication.
# ---------------------------------------------------------------------------
def floor_mul(cents, rate):
    """floor(cents * rate) using exact Decimal arithmetic, integer cents in/out."""
    result = (Decimal(int(cents)) * Decimal(str(rate))).to_integral_value(rounding=ROUND_FLOOR)
    return int(result)


def floor_div(numerator, denominator):
    return numerator // denominator


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def paginate(items):
    """Sort by created_at ascending then apply limit/offset.

    Returns (page_items, limit, offset, total_count).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            raise err(ERR_INVALID_REQUEST, "limit must be at least 1")
        if limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit may not exceed 100")

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be at least 0")

    # PRD §2.3: ascending created_at. The frozen logical clock can make
    # created_at strings identical, so break ties by the monotonic creation
    # sequence (true creation order), not the random UUID.
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
