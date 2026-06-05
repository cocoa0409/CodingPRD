"""Shared request-parsing, pagination, and lookup helpers.

These centralize the validation-priority ordering from PRD §3.12 so route
handlers apply checks consistently:
    1 auth (handled in middleware)
    2 role (handled in route via require_roles)
    3 existence (path ids + body FKs), left-to-right
    4 resource-owner
    5 segregation of duties
    6 invalid state
    7 dependent-state block
    8 survey lock
    9 invalid field (enum/range)
    ... business constraints ...
    last: ERR_VALIDATION (malformed body / missing required field)
"""
from datetime import datetime, timezone

from flask import request

import db
from errors import err


def parse_datetime(value, error_id="ERR_INVALID_FIELD", field="datetime"):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' (UTC). A malformed value surfaces as the given
    error_id (default ERR_INVALID_FIELD for a field-range failure).
    """
    if not isinstance(value, str):
        raise err(error_id, "%s must be an ISO 8601 datetime string." % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise err(error_id, "%s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# Pagination defaults (PRD §2.3 / SCAFFOLD §1.0).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_json_body():
    """Parse the request body as JSON.

    A malformed (non-JSON) body surfaces as ERR_VALIDATION (PRD §3.12). An
    absent body is treated as an empty object so that action endpoints with no
    required body fields still work.
    """
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body is not well-formed JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    """Required field presence (PRD §3.12 -> ERR_VALIDATION)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % f)


def parse_pagination():
    """Validate and return (limit, offset) -> ERR_PAGINATION_INVALID on bounds."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err("ERR_PAGINATION_INVALID", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0.")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (PRD §2.3) using the stable _seq tiebreak,
    then slice. Returns (page, total_count).
    """
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def lookup(store, resource_id):
    """Existence check -> ERR_NOT_FOUND (PRD §2.5)."""
    record = store.get(resource_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return record


def lookup_fk(store, fk_value):
    """Body-FK existence check -> ERR_NOT_FOUND (PRD §2.5)."""
    record = store.get(fk_value)
    if record is None:
        raise err("ERR_NOT_FOUND", "Referenced resource not found.")
    return record


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def require_int_field(body, name, minimum=None):
    """Field-range validity (PRD §3.12 -> ERR_INVALID_FIELD) for an integer."""
    val = body[name]
    if not is_int(val):
        raise err("ERR_INVALID_FIELD", "%s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_FIELD", "%s must be >= %s." % (name, minimum))
    return val


def require_number_field(body, name, minimum=None, strictly_positive=False):
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_FIELD", "%s must be a number." % name)
    if strictly_positive and not (val > 0):
        raise err("ERR_INVALID_FIELD", "%s must be > 0." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_FIELD", "%s must be >= %s." % (name, minimum))
    return val


def require_enum(body, name, allowed):
    val = body[name]
    if val not in allowed:
        raise err("ERR_INVALID_FIELD", "%s must be one of %s." % (name, sorted(allowed)))
    return val


def recompute_balance(job):
    """balance_due = gross - paid - waived - refunded (PRD §2.7)."""
    job["balance_due_cents"] = (
        job["gross_charges_cents"]
        - job["paid_cents"]
        - job["waived_cents"]
        - job["refunded_cents"]
    )
