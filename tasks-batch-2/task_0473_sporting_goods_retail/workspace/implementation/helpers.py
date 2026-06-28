"""Shared request-parsing, pagination, money, and serialization helpers."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import request

import errors


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict. Missing/empty body -> {}. Non-object -> 422."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Body is not valid JSON")
    if data is None:
        # Either no body or unparseable; treat absent body as empty object.
        if request.data.strip() == b"":
            return {}
        raise errors.invalid_request("Body is not valid JSON")
    if not isinstance(data, dict):
        raise errors.invalid_request("Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("Missing required field: %s" % f)


def as_int(body, field, required=True, minimum=None, maximum=None):
    """Coerce a field to int. Booleans are rejected; non-int strings/floats -> 422."""
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s below minimum %s" % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field %s above maximum %s" % (field, maximum))
    return val


def as_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request("Field %s must be a boolean" % field)
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request("Field %s must be a string" % field)
    return val


def as_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        raise errors.invalid_request("Field %s must be one of %s" % (field, sorted(choices)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Parse limit/offset query params. Returns (limit, offset).

    limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0). Out of
    bounds -> ERR_VALIDATION_PAGINATION (422).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.pagination("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.pagination("limit must be in [1, 100]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.pagination("offset must be an integer")
        if offset < 0:
            raise errors.pagination("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (tiebreak by creation sequence), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.8)
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) -> int cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_ceil(numerator, denominator):
    """ceil(numerator / denominator) -> int cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return int(q)
