"""Entity lifecycle helpers and shared validation primitives.

Common fields (PRD 2.4):
  - Mutable resources carry id, created_at, updated_at, version (starts at 1).
  - Immutable resources (Skill, InvoiceLineItem) carry only id, created_at.
  - Any mutation refreshes updated_at and increments version by 1 — INCLUDING
    recomputation of a derived field as a side effect of another action.
"""

from datetime import datetime, timezone

import db
import errors
from errors import ApiError


def init_mutable(record):
    """Stamp id/created_at/updated_at/version onto a new mutable record."""
    now = db.now_iso()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def init_immutable(record):
    """Stamp id/created_at onto a new immutable record (Skill, line item)."""
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    return record


def touch(record):
    """Register a mutation: refresh updated_at, bump version."""
    record["updated_at"] = db.now_iso()
    record["version"] = record["version"] + 1


# --- typed-field validation primitives (priority 4: ERR_VALIDATION, 422) ---

def _fail():
    raise ApiError(errors.ERR_VALIDATION, 422, "Request body validation failed.")


def require(body, field):
    if field not in body or body[field] is None:
        _fail()
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        _fail()
    return val


def require_int(body, field):
    val = require(body, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        _fail()
    return val


def require_number(body, field):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _fail()
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        _fail()
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        _fail()
    return val


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _fail()
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        _fail()
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        _fail()
    return val


def parse_iso(body, field):
    """Validate that a field is an ISO 8601 datetime string; return a
    comparable datetime. Malformed -> ERR_VALIDATION."""
    raw = require_str(body, field)
    return _parse_dt(raw)


def _parse_dt(raw):
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _fail()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# --- existence lookups (priority 3: ERR_*_NOT_FOUND, 404) ---

def get_or_404(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "Resource not found.")
    return rec
