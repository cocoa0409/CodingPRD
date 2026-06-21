"""Shared helpers: common-field stamping, body parsing, pagination, rounding."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store


# --- common system fields (PRD 2.4) -----------------------------------------
def stamp_create(rec):
    """Attach id, created_at, updated_at, version=1 to a new record."""
    now = store.now_iso()
    rec["id"] = store.new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version by 1."""
    rec["updated_at"] = store.now_iso()
    rec["version"] = rec.get("version", 0) + 1
    return rec


# --- request body parsing ----------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} for an empty body.

    A malformed (non-JSON) body or a non-object JSON value is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def fk(body, name):
    """Return a present, string-typed FK id for existence resolution.

    A missing/non-string FK is a structural error (ERR_INVALID_REQUEST). When
    present and a string, the id is handed to a lookup that raises ERR_NOT_FOUND
    if no such resource exists, preserving the existence-before-structure order
    across multiple FKs resolved left-to-right.
    """
    val = body.get(name)
    if not isinstance(val, str):
        raise errors.invalid_request("Missing or invalid field: %s" % name)
    return val


def as_int(body, name, required=True, default=None, non_negative=True):
    """Read an integer cents/count field.

    booleans are rejected (Python bool is an int subclass). Non-negative is
    enforced for cents fields per validation priority 5.
    """
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer" % name)
    if non_negative and val < 0:
        raise errors.invalid_request("Field %s must be a non-negative integer" % name)
    return val


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string" % name)
    return val


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean" % name)
    return val


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    val = body[name]
    if val not in allowed:
        raise errors.invalid_request("Field %s must be one of %s" % (name, sorted(allowed)))
    return val


# --- pagination (PRD 2.3) ----------------------------------------------------
def pagination():
    """Read limit (default 10, min 1, max 100) and offset (default 0)."""
    limit = _int_query("limit", 10, minimum=1, maximum=100)
    offset = _int_query("offset", 0, minimum=0, maximum=None)
    return limit, offset


def _int_query(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        raise errors.invalid_request("Query param %s must be an integer" % name)
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    """Stable ascending sort by created_at (PRD 2.3 default ordering)."""
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


# --- rounding (PRD 2.7) ------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half-up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
