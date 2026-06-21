"""Shared parsing, validation, serialization, and pagination helpers."""
from datetime import datetime, timezone

from flask import request

import errors

# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON body as a dict. Missing/empty body -> {}.

    A malformed (non-JSON) body that is present is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request("Illegal value for %s." % field)


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC). Returns aware datetime in UTC.
# ---------------------------------------------------------------------------


def parse_dt(value, field):
    if not isinstance(value, str):
        raise errors.invalid_request("Field %s must be an ISO 8601 string." % field)
    s = value.strip()
    raw = s
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        # Treat naive as UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt, raw


def whole_minutes(start_dt, end_dt):
    """floor((end - start) / 60 seconds) in whole minutes."""
    delta = (end_dt - start_dt).total_seconds()
    return int(delta // 60)


# ---------------------------------------------------------------------------
# Numeric parsing
# ---------------------------------------------------------------------------


def parse_number(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % field)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    return value


def parse_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("Field %s must be >= %s." % (field, minimum))
    return value


def parse_bool(value, field):
    if not isinstance(value, bool):
        raise errors.invalid_request("Field %s must be a boolean." % field)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — ERR_VALIDATION (422) when out of range.
# ---------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_error("limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.validation_error("limit out of range.")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_error("offset must be an integer.")
        if offset < OFFSET_MIN:
            raise errors.validation_error("offset out of range.")

    return limit, offset


def paginate(records):
    """Sort by created_at asc (tie-broken by creation sequence), then page.

    Returns (page_items_serialized_caller, limit, offset, total_count) — caller
    serializes; here we return the raw slice plus pagination metadata.
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Serialization — strip internal fields (those prefixed with "_").
# ---------------------------------------------------------------------------


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_list(records):
    return [serialize(r) for r in records]
