"""Shared validation helpers (PRD §2.3, §2.7, §3 body rules)."""

from decimal import Decimal, InvalidOperation

from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_PAGINATION_INVALID,
)


def get_body():
    """Return the JSON body as a dict; tolerate empty/no body as {}."""
    from flask import request

    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Body must be a JSON object.")
    return data


def require_found(entity):
    """Raise ERR_NOT_FOUND when a looked-up entity is missing (priority 3)."""
    if entity is None:
        raise err(ERR_NOT_FOUND, "Referenced resource does not exist.")
    return entity


def parse_pagination(args):
    """Validate and return (limit, offset). Raises ERR_PAGINATION_INVALID.

    limit defaults 10, min 1, max 100; offset defaults 0, min 0. (§2.3)
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer.")
        if str(limit) != str(limit_raw).strip():
            # reject e.g. "10.5" or non-canonical numerics
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer.")

    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer.")
        if str(offset) != str(offset_raw).strip():
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer.")

    if limit < 1 or limit > 100:
        raise err(ERR_PAGINATION_INVALID, "limit out of bounds (1..100).")
    if offset < 0:
        raise err(ERR_PAGINATION_INVALID, "offset must be >= 0.")
    return limit, offset


def sort_and_paginate(rows, limit, offset):
    """Sort by created_at ascending (stable on _seq) and slice (§2.3)."""
    ordered = sorted(rows, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return page, total


# ---- field-level body validators (priority 4: ERR_INVALID_REQUEST) ----


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}.")
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"{name} must be a non-empty string.")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{name} must be one of {sorted(allowed)}.")
    return val


def require_country(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or len(val) != 2 or not val.isalpha() or val != val.upper():
        raise err(ERR_INVALID_REQUEST, f"{name} must be 2 uppercase letters.")
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"{name} must be an integer.")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"{name} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"{name} must be <= {maximum}.")
    return val


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a boolean.")
    return val


def to_decimal(value, name):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise err(ERR_INVALID_REQUEST, f"{name} must be a number.")
