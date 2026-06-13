"""Shared field-level validation + pagination helpers.

Field-level request validation is the lowest-priority gate (PRD §2.6) and
yields ERR_INVALID_REQUEST (400).
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST


def get_json_body():
    """Parse the JSON body; tolerate empty bodies as {} for action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        # Body present but not valid JSON.
        if request.data.strip():
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {n}")


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def as_nonempty_str(body, name, required=True, default=None):
    v = as_str(body, name, required=required, default=default)
    if v is not None and v.strip() == "":
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be non-empty")
    return v


def as_int(body, name, required=True, default=None, minimum=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    # bool is a subclass of int — reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return v


def as_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    v = body[name]
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---- pagination (PRD §2.3) ----
def parse_pagination():
    """Return (limit, offset). limit default 10, min 1, max 100; offset default 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (tie-break by creation sequence), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
