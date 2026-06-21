"""Request-body field validation and pagination parsing.

Malformed bodies (missing required field, bad enum, bad phone, negative
integer where non-negative required, deposit_pct out of [0,1], ...) raise
ERR_VALIDATION (PRD §2.10). Pagination out of bounds raises
ERR_PAGINATION_INVALID (PRD §2.3).
"""
import re

from flask import request

from errors import (
    err, ERR_VALIDATION, ERR_PAGINATION_INVALID, ERR_NOT_FOUND,
)

PHONE_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")

# Pagination defaults (PRD §2.3 / scaffold §1.0).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_body():
    """Return the JSON body as a dict (empty dict if none / non-object)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_VALIDATION, f"missing required field: {field}")
    return body[field]


def require_str(body, field, allow_empty=False, max_len=None):
    val = require(body, field)
    if not isinstance(val, str):
        raise err(ERR_VALIDATION, f"{field} must be a string")
    if not allow_empty and val.strip() == "":
        raise err(ERR_VALIDATION, f"{field} must be non-empty")
    if max_len is not None and len(val) > max_len:
        raise err(ERR_VALIDATION, f"{field} exceeds {max_len} characters")
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(ERR_VALIDATION, f"{field} must be a string")
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_VALIDATION, f"{field} must be an integer")
    _check_int_bounds(val, field, minimum, maximum)
    return val


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_VALIDATION, f"{field} must be an integer")
    _check_int_bounds(val, field, minimum, maximum)
    return val


def _check_int_bounds(val, field, minimum, maximum):
    if minimum is not None and val < minimum:
        raise err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_VALIDATION, f"{field} must be <= {maximum}")


def require_number(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_VALIDATION, f"{field} must be a number")
    if minimum is not None and val < minimum:
        raise err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_VALIDATION, f"{field} must be <= {maximum}")
    return val


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_number(body, field, minimum, maximum)


def require_enum(body, field, choices):
    val = require(body, field)
    if val not in choices:
        raise err(ERR_VALIDATION, f"{field} must be one of {sorted(choices)}")
    return val


def opt_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, choices)


def require_phone(body, field):
    val = require_str(body, field)
    if not PHONE_RE.match(val):
        raise err(ERR_VALIDATION, f"{field} must be a valid E.164 phone")
    return val


def require_time_str(body, field):
    """HH:MM 24h."""
    val = require_str(body, field)
    if not re.match(r"^([01][0-9]|2[0-3]):[0-5][0-9]$", val):
        raise err(ERR_VALIDATION, f"{field} must be HH:MM 24h")
    return val


def require_last4(body, field):
    val = require(body, field)
    if not isinstance(val, str) or not re.match(r"^[0-9]{4}$", val):
        raise err(ERR_VALIDATION, f"{field} must be 4 digits")
    return val


def parse_pagination():
    """Parse limit/offset query params. Returns (limit, offset)."""
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(ERR_PAGINATION_INVALID, "limit out of bounds")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise err(ERR_PAGINATION_INVALID, "offset must not be negative")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (creation order), apply limit/offset, and
    return (page, pagination_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination
