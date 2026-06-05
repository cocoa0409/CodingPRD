"""Shared helpers: serialization, pagination, body parsing, validation.

These helpers centralise behaviour that is identical across resource routes:
the public field projection (stripping internal bookkeeping like `_seq`),
created_at-ASC pagination (PRD §2.3), and field-level body validation
(ERR_INVALID_REQUEST, PRD §2.8, priority 15).
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

# Internal-only keys that never appear in API output.
_PRIVATE_KEYS = {"_seq"}

# Pagination defaults (scaffold response_envelope.pagination_defaults / PRD §2.3).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def public(obj):
    """Project a stored record to its public representation (drop private keys)."""
    return {k: v for k, v in obj.items() if k not in _PRIVATE_KEYS}


def round_half_up_cents(value):
    """Round a Decimal/number to a whole integer using ROUND_HALF_UP (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to two decimal places using ROUND_HALF_UP (PRD §2.6), as a float."""
    q = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# --- Body parsing -----------------------------------------------------------
def get_json_body():
    """Return the parsed JSON object body, or {} when absent.

    A malformed JSON body (not a JSON object) is a field-shape violation.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # Empty/absent body is treated as {} for actions that take no input.
        if not request.data:
            return {}
        raise errors.invalid_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """ERR_INVALID_REQUEST if any required field is missing or null."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request(f"Invalid value for {field}: {value!r}")


def require_int(value, field, *, minimum=None, maximum=None):
    """Validate an integer field; bools are rejected (they subclass int)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise errors.invalid_request(f"{field} must be <= {maximum}")
    return value


def require_number(value, field, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"{field} must be a number")
    if minimum is not None and value < minimum:
        raise errors.invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise errors.invalid_request(f"{field} must be <= {maximum}")
    return value


def require_string(value, field):
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request(f"{field} must be a non-empty string")
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise errors.invalid_request(f"{field} must be a boolean")
    return value


# --- Pagination -------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    Out-of-range or non-integer values are field-shape violations
    (ERR_INVALID_REQUEST, 400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise errors.invalid_request(
                f"limit must be between {PAGE_LIMIT_MIN} and {PAGE_LIMIT_MAX}"
            )

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ASC (insertion sequence) and slice (PRD §2.3).

    Returns (page_rows, pagination_meta).
    """
    ordered = sorted(rows, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return [public(r) for r in window], pagination
