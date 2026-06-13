"""Shared request-parsing & validation helpers for route handlers."""

from flask import request

import errors
import response
import db


# ---- Body parsing --------------------------------------------------------

def get_json_body():
    """Return the JSON body as a dict. Missing/invalid body -> {} (so required-field
    checks fire ERR_INVALID_REQUEST rather than a 500)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    """Ensure every name in `fields` is present (not None) in body (priority 4)."""
    for f in fields:
        if body.get(f) is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    return val


def required_int(body, field):
    val = body.get(field)
    if val is None or isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean.")
    return val


def optional_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number.")
    return val


def enum_value(body, field, allowed, default=None, required=False):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request(f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request(f"Invalid value for {field}: {val!r}")
    return val


# ---- Existence lookups (ERR_NOT_FOUND, priority 3) -----------------------

def find_or_404(collection, ident):
    rec = collection.get(ident)
    if rec is None:
        raise errors.not_found(f"Resource {ident} not found.")
    return rec


# ---- Pagination & list filtering -----------------------------------------

def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults 10, range [1,100]; offset defaults 0, must be >= 0. Invalid ->
    ERR_VALIDATION_PARAM (400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_param("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation_param("limit must be in [1, 100].")

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_param("offset must be an integer.")
        if offset < 0:
            raise errors.validation_param("offset must be >= 0.")

    return limit, offset


def enum_filter(param, allowed):
    """Read a query-string enum filter; unknown value -> ERR_VALIDATION_PARAM."""
    val = request.args.get(param)
    if val is None:
        return None
    if val not in allowed:
        raise errors.validation_param(f"Unknown {param} filter value: {val!r}")
    return val


def list_response(records, serializer):
    """Sort by created_at ASC, paginate, and emit an array envelope."""
    limit, offset = parse_pagination()
    ordered = db.sorted_by_created(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    items = [serializer(r) for r in page]
    return response.array_response(items, limit, offset, total)
