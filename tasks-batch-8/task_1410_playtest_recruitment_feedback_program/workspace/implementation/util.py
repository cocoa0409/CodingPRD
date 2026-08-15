"""Shared helpers: entity factory, serialization, validation utilities."""

import re
import uuid
from datetime import datetime, timezone, timedelta

import db
from db import _parse_iso, _format_iso
from errors import raise_error, ERR_INVALID_REQUEST, ERR_WINDOW_VIOLATION


def new_id():
    return str(uuid.uuid4())


def mint_key_code():
    """KEY- followed by 12 uppercase alphanumeric characters."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    suffix = "".join(random_choice(alphabet) for _ in range(12))
    return "KEY-" + suffix


import random as _random


def random_choice(alphabet):
    return _random.choice(alphabet)


def stamp_new(rec):
    """Stamp a freshly created entity with id/created_at/updated_at/version."""
    now = db.clock.now()
    rec["id"] = new_id()
    rec["created_at"] = _format_iso(now)
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_created_sort"] = _format_iso(now)
    rec["_seq"] = db.next_seq()
    return rec


def stamp_new_append_only(rec):
    """Stamp an append-only record (ExposureRecord): id + created_at only."""
    now = db.clock.now()
    rec["id"] = new_id()
    rec["created_at"] = _format_iso(now)
    rec["_created_sort"] = _format_iso(now)
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation."""
    rec["updated_at"] = _format_iso(db.clock.now())
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Request payload helpers
# ---------------------------------------------------------------------------

def get_payload():
    from flask import request
    if not request.is_json:
        data = request.get_json(silent=True)
        if data is None:
            return {}
        return data
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def optional_string(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be a string" % name)
    return v


def require_int(body, name, minimum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    return v


def optional_int(body, name, default=None, minimum=None):
    v = body.get(name, default)
    if v is None:
        return v
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    return v


def require_number(body, name, minimum=None, maximum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (name, maximum))
    return v


def require_array(body, name):
    v = require_field(body, name)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be an array" % name)
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def require_datetime(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 string" % name)
    try:
        return _parse_iso(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "Field %s must be a valid ISO 8601 timestamp" % name)


def validate_window(starts_at, ends_at):
    """ends_at must be strictly after starts_at, else ERR_WINDOW_VIOLATION (422)."""
    if ends_at <= starts_at:
        raise_error(ERR_WINDOW_VIOLATION, "ends_at must be strictly after starts_at")


def check_unique(store, field, value, exclude_id=None):
    for rec in store.values():
        if rec.get(field) == value and rec.get("id") != exclude_id:
            raise_error(ERR_INVALID_REQUEST, "Value for %s must be unique" % field)
