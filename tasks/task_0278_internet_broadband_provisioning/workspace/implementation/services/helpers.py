"""Shared request helpers: body parsing, existence lookups, pagination, ownership."""
from flask import request

import db
from errors import err
from timeutil import parse_iso


def get_json_body():
    """Return the JSON body as a dict; non-dict / unparseable -> ERR_INVALID_REQUEST."""
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        # No body supplied.
        if request.data:
            err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def lookup(collection, resource_id):
    """Existence check (priority 3). Returns the record or raises ERR_NOT_FOUND."""
    rec = collection.get(resource_id)
    if rec is None:
        err("ERR_NOT_FOUND", "Referenced resource %s does not exist." % resource_id)
    return rec


def require_fields(body, names):
    """All named fields must be present and non-null (priority 4)."""
    for n in names:
        if n not in body or body[n] is None:
            err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_positive_int(body, name):
    val = body.get(name)
    if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
        err("ERR_INVALID_REQUEST", "Field %s must be a positive integer." % name)
    return val


def require_int(body, name):
    val = body.get(name)
    if not isinstance(val, int) or isinstance(val, bool):
        err("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    return val


def require_iso(body, name):
    val = body.get(name)
    dt = parse_iso(val) if val is not None else None
    if dt is None:
        err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 timestamp." % name)
    return dt


def require_enum(body, name, allowed):
    val = body.get(name)
    if val not in allowed:
        err("ERR_INVALID_REQUEST",
            "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def paginate(records):
    """Apply §2.3 pagination over a list pre-sorted ascending by created_at.

    Returns (window, limit, offset, total_count, has_more).
    limit default 10 (min 1, max 100); offset default 0 (no upper bound).
    Out-of-bounds -> ERR_INVALID_REQUEST.
    """
    args = request.args
    limit = _parse_int_param(args.get("limit"), 10)
    offset = _parse_int_param(args.get("offset"), 0)
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    total = len(records)
    window = records[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, limit, offset, total, has_more


def _parse_int_param(raw, default):
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def sorted_by_created(records):
    """Sort ascending by created_at, then id for stable tiebreak (§2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def check_owner(role, user_id, account):
    """Ownership check (priority 6): a Customer may act only on owned accounts."""
    if role == "Customer" and account.get("customer_user_id") != user_id:
        err("ERR_NOT_ACCOUNT_OWNER",
            "Customer does not own the target account.")
