"""Shared request helpers: body parsing, validation, pagination, lookups."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import (
    fail,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        data = request.get_json(silent=True)
        if data is None:
            fail(ERR_INVALID_REQUEST, "Request body must be valid JSON")
        if not isinstance(data, dict):
            fail(ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            fail(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def as_decimal(value, field):
    if isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    if not isinstance(value, (int, float, str)):
        fail(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(ERR_INVALID_REQUEST, f"Field {field} must be a number")


def positive_decimal(value, field):
    d = as_decimal(value, field)
    if d <= 0:
        fail(ERR_INVALID_REQUEST, f"Field {field} must be greater than zero")
    return d


def fraction(value, field):
    """0 < value <= 1."""
    d = as_decimal(value, field)
    if d <= 0 or d > 1:
        fail(ERR_INVALID_REQUEST, f"Field {field} must be in (0, 1]")
    return d


def require_int(value, field, lo=None, hi=None):
    if isinstance(value, bool):
        fail(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if not isinstance(value, int):
        if isinstance(value, str) and value.lstrip("-").isdigit():
            value = int(value)
        else:
            fail(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if lo is not None and value < lo:
        fail(ERR_INVALID_REQUEST, f"Field {field} below minimum")
    if hi is not None and value > hi:
        fail(ERR_INVALID_REQUEST, f"Field {field} above maximum")
    return value


def require_string(value, field):
    if not isinstance(value, str) or value == "":
        fail(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return value


def lookup(collection, _id):
    obj = collection.get(_id)
    if obj is None:
        fail(ERR_NOT_FOUND, "Referenced resource does not exist")
    return obj


def paginate(items):
    """Apply limit/offset query params (PRD §2.3). items already sorted."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            fail(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(ERR_INVALID_REQUEST, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            fail(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            fail(ERR_INVALID_REQUEST, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))
