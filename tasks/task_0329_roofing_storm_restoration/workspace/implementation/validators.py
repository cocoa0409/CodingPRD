"""Reusable validation primitives and money rounding.

The priority order from PRD §2.9 is enforced by *calling these in order* inside
each route:
  (1) auth, (2) forbidden  -> middleware.require_role
  (3) path existence       -> find_or_404
  (4) body FK resolution   -> resolve_fk
  (5) required field present-> require_field
  (6) enum/range/interval  -> validate_* (ERR_INVALID_REQUEST 422)
  (7) state                -> route-specific
  (8) cross-entity         -> route-specific
  (9) temporal             -> route-specific
  (10) fiscal              -> route-specific
  (11) OCC                 -> route-specific
"""
from decimal import Decimal, ROUND_HALF_UP

import errors
from errors import ApiError
from flask import request


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest integer using round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Path existence (priority 3) and FK resolution (priority 4)
# ---------------------------------------------------------------------------
def find_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Resource not found")
    return ent


def resolve_fk(collection, fk_value):
    """Resolve a body foreign key, raising ERR_FK_NOT_FOUND (404) if missing."""
    ent = collection.get(fk_value)
    if ent is None:
        raise ApiError(errors.ERR_FK_NOT_FOUND, 404, "Referenced resource not found")
    return ent


# ---------------------------------------------------------------------------
# Required-field presence (priority 5) -> ERR_MISSING_FIELD 400
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(errors.ERR_MISSING_FIELD, 400, "Missing required field: " + name)
    return body[name]


def missing_field(name):
    raise ApiError(errors.ERR_MISSING_FIELD, 400, "Missing required field: " + name)


# ---------------------------------------------------------------------------
# Enum / range / interval (priority 6) -> ERR_INVALID_REQUEST 422
# ---------------------------------------------------------------------------
def invalid_request(message="Invalid request"):
    raise ApiError(errors.ERR_INVALID_REQUEST, 422, message)


def validate_enum(value, allowed, field):
    if value not in allowed:
        invalid_request("Invalid value for " + field)
    return value


def validate_string(value, field):
    if not isinstance(value, str) or value == "":
        # presence/typing failure is treated as a missing/invalid field;
        # callers use require_field first, so this guards typing.
        raise ApiError(errors.ERR_MISSING_FIELD, 400, "Missing or invalid field: " + field)
    return value


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_number(value, field, gt=None, ge=None, lt=None, le=None):
    if not is_number(value):
        invalid_request("Field " + field + " must be a number")
    if gt is not None and not (value > gt):
        invalid_request(field + " must be > " + str(gt))
    if ge is not None and not (value >= ge):
        invalid_request(field + " must be >= " + str(ge))
    if lt is not None and not (value < lt):
        invalid_request(field + " must be < " + str(lt))
    if le is not None and not (value <= le):
        invalid_request(field + " must be <= " + str(le))
    return value


def validate_int(value, field, gt=None, ge=None, lt=None, le=None):
    if not is_int(value):
        invalid_request("Field " + field + " must be an integer")
    if gt is not None and not (value > gt):
        invalid_request(field + " must be > " + str(gt))
    if ge is not None and not (value >= ge):
        invalid_request(field + " must be >= " + str(ge))
    if lt is not None and not (value < lt):
        invalid_request(field + " must be < " + str(lt))
    if le is not None and not (value <= le):
        invalid_request(field + " must be <= " + str(le))
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) -> ERR_VALIDATION 400 on out-of-bounds
# ---------------------------------------------------------------------------
def parse_pagination():
    """Return (limit, offset). limit in [1,100] default 10; offset >= 0 default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_VALIDATION, 400, "limit out of bounds (1..100)")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(errors.ERR_VALIDATION, 400, "offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list already sorted by created_at asc; return (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
