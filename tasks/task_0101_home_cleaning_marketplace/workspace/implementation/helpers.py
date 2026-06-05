"""Per-request helpers shared by route handlers: body parsing, existence
resolution, ownership checks, pagination, list filtering.
"""
from flask import request

import db
from errors import err


def get_json_body():
    """Return the parsed JSON object body, or {} when absent.

    A body that is present but not a JSON object raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
    return data


def require_resource(collection, rid, label="resource"):
    """Resolve an id against a collection or raise ERR_NOT_FOUND.

    rid of None also raises ERR_NOT_FOUND (a referenced id that is required
    but missing is treated as unresolved — but callers should validate
    required-field presence separately when that is the intended error).
    """
    if rid is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "%s not found" % label)
    return rec


def ownership_customer(principal, customer_id):
    """ERR_FORBIDDEN_OWNERSHIP unless the acting Customer owns customer_id.

    PlatformAdmin bypasses ownership. Only enforced for Customer role.
    """
    if principal.role == "Customer" and principal.user_id != customer_id:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "customer does not own this resource")


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit defaults 10, min 1, max 100. offset defaults 0, min 0. Out-of-range
    or non-integer values raise ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (stable via _seq) and slice the page."""
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def require_fields(body, fields):
    """Ensure each named field is present and non-null; else ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "missing field: %s" % f)
