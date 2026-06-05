"""Shared helpers: common system fields, mutation bumps, request parsing,
pagination, and entity serialization (PRD §2.3, §2.4)."""

from flask import request

from db import db, new_id
from errors import invalid_request, validation_range
from util import format_iso_millis


# --- Common system fields (PRD §2.4) -----------------------------------------
def stamp_new(entity, with_version=True):
    """Stamp id/created_at/updated_at/version on a freshly created entity.

    The clock used for created_at/updated_at is the *real* wall time in §2.4 terms
    ("first creation"/"last modification"). These bookkeeping timestamps are
    independent of the logical clock (which governs business datetimes only).
    """
    now = format_iso_millis(db.clock)
    entity["id"] = new_id()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def bump(entity):
    """Record a mutation: refresh updated_at and increment version (PRD §2.4)."""
    if "version" in entity:
        entity["version"] = entity.get("version", 1) + 1
        entity["updated_at"] = format_iso_millis(db.clock)
    return entity


# --- Request body parsing -----------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none/empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object.")
    return body


def require_field(body, name, types=None, enum=None):
    """Fetch a required field, validating presence, type, and enum membership.

    Missing/wrong-type/bad-enum -> ERR_INVALID_REQUEST (PRD §2.6, §1.4 priority 5).
    """
    if name not in body or body[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    value = body[name]
    if types is not None and not isinstance(value, types):
        raise invalid_request("Field %s has the wrong type." % name)
    if isinstance(value, bool) and types is not None and bool not in _as_tuple(types):
        raise invalid_request("Field %s has the wrong type." % name)
    if enum is not None and value not in enum:
        raise invalid_request("Field %s must be one of %s." % (name, sorted(enum)))
    return value


def optional_field(body, name, types=None, enum=None, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if types is not None and not isinstance(value, types):
        raise invalid_request("Field %s has the wrong type." % name)
    if isinstance(value, bool) and types is not None and bool not in _as_tuple(types):
        raise invalid_request("Field %s has the wrong type." % name)
    if enum is not None and value not in enum:
        raise invalid_request("Field %s must be one of %s." % (name, sorted(enum)))
    return value


def _as_tuple(types):
    return types if isinstance(types, tuple) else (types,)


def require_int(body, name):
    """Required integer field (rejecting bools), ERR_INVALID_REQUEST on failure."""
    if name not in body or body[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer." % name)
    return value


def optional_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field %s must be an integer." % name)
    return value


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid_request("Field %s must be a boolean." % name)
    return value


# --- Pagination (PRD §2.3) ----------------------------------------------------
def parse_pagination():
    """Read limit/offset query params, applying defaults and range checks.

    limit default 10, min 1, max 100 (out of range -> ERR_VALIDATION_RANGE).
    offset default 0.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise validation_range("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer.")
        if offset < 0:
            raise invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ascending (PRD §2.3) and slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --- Serialization ------------------------------------------------------------
# Field order per entity is informational; JSON object key order does not affect
# test equality. We serialize a shallow copy so internal-only keys can be hidden.
def serialize(entity, hidden=()):
    out = {}
    for k, v in entity.items():
        if k in hidden:
            continue
        out[k] = v
    return out
