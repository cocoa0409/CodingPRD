"""Shared helpers: common fields, validation, pagination, time parsing."""
from datetime import datetime, timezone

import errors
from errors import ApiError
from db import db, new_id, now_iso, iso


# -----------------------------------------------------------------------------
# Common system fields (PRD §2.4): id, created_at, updated_at, version.
# -----------------------------------------------------------------------------
def init_common(record):
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mutation bump: refresh updated_at, increment version by exactly 1."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


def public(record):
    """Strip internal-only keys (those prefixed with '_') from a record."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# -----------------------------------------------------------------------------
# Request-body validation helpers.
# -----------------------------------------------------------------------------
def invalid(message="Invalid request"):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, message)


def get_body():
    from flask import request
    if request.is_json:
        body = request.get_json(silent=True)
    else:
        body = request.get_json(silent=True, force=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        invalid("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            invalid("Missing required field: %s" % f)


def require_positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        invalid("%s must be a positive integer" % name)
    return value


def require_nonneg_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        invalid("%s must be a non-negative integer" % name)
    return value


# -----------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0.
# -----------------------------------------------------------------------------
def parse_pagination(args):
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (tie-break on insertion seq) then window."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [public(r) for r in window], total


# -----------------------------------------------------------------------------
# Existence resolution (PRD §2.5): left-to-right, first miss -> ERR_NOT_FOUND.
# -----------------------------------------------------------------------------
def resolve(collection, resource_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found")
    return rec


# -----------------------------------------------------------------------------
# Time parsing for ISO 8601 instants supplied in request bodies.
# -----------------------------------------------------------------------------
def parse_instant(value, name):
    if not isinstance(value, str):
        invalid("%s must be an ISO 8601 string" % name)
    raw = value
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        invalid("%s is not a valid ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
