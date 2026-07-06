"""Shared utilities: rounding, pagination, JSON parsing helpers."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import request

import errors
import db


def round_half_up_cents(amount) -> int:
    """Round a Decimal / int / float amount (already in cents) to integer cents using HALF_UP."""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return int(amount.to_integral_value(rounding=ROUND_HALF_UP))


def get_body() -> dict:
    """Parse JSON body, defaulting to {} on empty. Raise ERR_INVALID_REQUEST on malformed."""
    if request.content_length in (None, 0):
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "body must be an object")
    return body


def get_str(body: dict, field: str, required: bool = True, allow_empty: bool = False):
    v = body.get(field)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return None
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a string")
    if not allow_empty and v == "" and required:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return v


def get_int(body: dict, field: str, required: bool = True, default=None):
    if field not in body or body.get(field) is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return default
    v = body[field]
    # In JSON, booleans are separate from ints but bool is subclass of int in Python. Reject bool.
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be an integer")
    return v


def get_number(body: dict, field: str, required: bool = True, default=None):
    if field not in body or body.get(field) is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a number")
    if not isinstance(v, (int, float)):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a number")
    return v


def get_bool(body: dict, field: str, required: bool = False, default=None):
    if field not in body or body.get(field) is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def get_enum(body: dict, field: str, allowed: list[str], required: bool = True, default=None):
    v = body.get(field)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return default
    if not isinstance(v, str) or v not in allowed:
        errors.raise_error(
            errors.ERR_INVALID_REQUEST,
            f"{field} must be one of {allowed}",
        )
    return v


def get_iso_datetime(body: dict, field: str, required: bool = True, default=None):
    v = body.get(field)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return default
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    try:
        return db.parse_iso(v)
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a valid ISO 8601 timestamp")


def get_iso_date(body: dict, field: str, required: bool = True):
    v = body.get(field)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
        return None
    if not isinstance(v, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 date")
    # Expect YYYY-MM-DD
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"{field} must be a valid YYYY-MM-DD date")
    return v


def get_pagination():
    """Extract limit and offset from query string, with validation."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be non-negative")
    return limit, offset


def apply_pagination(items, limit: int, offset: int):
    return items[offset : offset + limit], len(items)


def sort_by_created_at(items):
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
