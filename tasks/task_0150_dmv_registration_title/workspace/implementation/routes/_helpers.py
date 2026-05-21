"""Shared route helpers — pagination, validation primitives, OCC, body parsing."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import make_error
from utils import parse_iso8601, to_decimal


# -----------------------------------------------------------------------------
# Pagination
# -----------------------------------------------------------------------------
def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100.
    offset default 0, min 0.
    Invalid values raise ERR_VALIDATION.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else PAGINATION_DEFAULT_LIMIT
        offset = int(offset_raw) if offset_raw is not None else PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise make_error("ERR_VALIDATION", "limit/offset must be integers.")
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise make_error("ERR_VALIDATION", "limit out of range [1, 100].")
    if offset < PAGINATION_DEFAULT_OFFSET:
        raise make_error("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def build_pagination_meta(limit: int, offset: int, total_count: int) -> dict:
    return {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }


def paginate_and_sort(rows: list[dict], limit: int, offset: int, *,
                      sort_key: str = "created_at") -> tuple[list[dict], int]:
    """Sort by `sort_key` ASC (with stable secondary on id) and slice."""
    total = len(rows)
    rows_sorted = sorted(rows, key=lambda r: (r.get(sort_key) or "", r.get("id", "")))
    return rows_sorted[offset: offset + limit], total


# -----------------------------------------------------------------------------
# Field validators (raise ERR_VALIDATION on failure)
# -----------------------------------------------------------------------------
def require_field(body: dict, key: str):
    if key not in body or body[key] is None:
        raise make_error("ERR_VALIDATION", f"Missing required field: {key}.")
    return body[key]


def require_str(value, name: str, *, min_len: int | None = None,
                max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise make_error("ERR_VALIDATION", f"{name} must be a string.")
    if min_len is not None and len(value) < min_len:
        raise make_error("ERR_VALIDATION", f"{name} is too short.")
    if max_len is not None and len(value) > max_len:
        raise make_error("ERR_VALIDATION", f"{name} is too long.")
    return value


def require_int(value, name: str, *, min_value: int | None = None,
                max_value: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise make_error("ERR_VALIDATION", f"{name} must be an integer.")
    if min_value is not None and value < min_value:
        raise make_error("ERR_VALIDATION", f"{name} below minimum.")
    if max_value is not None and value > max_value:
        raise make_error("ERR_VALIDATION", f"{name} above maximum.")
    return value


def require_bool(value, name: str) -> bool:
    if not isinstance(value, bool):
        raise make_error("ERR_VALIDATION", f"{name} must be a boolean.")
    return value


def require_decimal(value, name: str, *, min_value: Decimal | None = None,
                    max_value: Decimal | None = None,
                    max_decimal_places: int = 2) -> Decimal:
    if isinstance(value, bool):
        raise make_error("ERR_VALIDATION", f"{name} must be a number.")
    try:
        dec = to_decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise make_error("ERR_VALIDATION", f"{name} must be a number.")
    # Enforce max_decimal_places
    sign, digits, exp = dec.as_tuple()
    if exp < -max_decimal_places:
        raise make_error("ERR_VALIDATION", f"{name} has more than {max_decimal_places} decimal places.")
    if min_value is not None and dec < min_value:
        raise make_error("ERR_VALIDATION", f"{name} below minimum.")
    if max_value is not None and dec > max_value:
        raise make_error("ERR_VALIDATION", f"{name} above maximum.")
    return dec


def require_enum(value, name: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise make_error("ERR_VALIDATION", f"{name} must be one of {sorted(allowed)}.")
    return value


def require_iso8601(value, name: str) -> datetime:
    if not isinstance(value, str):
        raise make_error("ERR_VALIDATION", f"{name} must be an ISO 8601 datetime.")
    try:
        return parse_iso8601(value)
    except (ValueError, TypeError):
        raise make_error("ERR_VALIDATION", f"{name} is not a valid ISO 8601 datetime.")


# -----------------------------------------------------------------------------
# Optimistic concurrency
# -----------------------------------------------------------------------------
def check_occ(body: dict, entity: dict) -> None:
    """If body['version'] is present, compare against entity['version'].

    Mismatch -> ERR_VERSION_CONFLICT. Missing/None -> skipped (PRD §2.5).
    """
    if "version" in body and body["version"] is not None:
        provided = body["version"]
        if not isinstance(provided, int) or isinstance(provided, bool):
            raise make_error("ERR_VALIDATION", "version must be an integer.")
        if provided != entity.get("version"):
            raise make_error("ERR_VERSION_CONFLICT")
