"""Validation, pagination, and serialization helpers."""
import json
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def get_body():
    body = None
    raw = request.get_data(cache=True)
    if raw and raw.strip():
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            # Fall back to parsing the raw bytes (e.g. when the client did not
            # set Content-Type: application/json).
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return value


def check_enum(value, field, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# ---------------------------------------------------------------------------
def get_pagination():
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
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
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


def paginate(rows, limit, offset):
    """rows: list of entity dicts. Sort by created_at ASC (seq tie-break)."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
