"""Schema/field-type validation helpers."""

from decimal import Decimal, InvalidOperation

from errors import err
from clock import parse_iso8601


def require_dict(body):
    if not isinstance(body, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_int(value, *, field: str, min_val=None, max_val=None):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", f"{field} must be an integer.")
    if min_val is not None and value < min_val:
        err("ERR_VALIDATION", f"{field} must be >= {min_val}.")
    if max_val is not None and value > max_val:
        err("ERR_VALIDATION", f"{field} must be <= {max_val}.")
    return value


def require_str(value, *, field: str, min_len=1, max_len=None):
    if not isinstance(value, str):
        err("ERR_VALIDATION", f"{field} must be a string.")
    if min_len is not None and len(value) < min_len:
        err("ERR_VALIDATION", f"{field} length must be >= {min_len}.")
    if max_len is not None and len(value) > max_len:
        err("ERR_VALIDATION", f"{field} length must be <= {max_len}.")
    return value


def require_enum(value, choices, *, field: str):
    if value not in choices:
        err("ERR_VALIDATION", f"{field} must be one of {sorted(choices)}.")
    return value


def require_number(value, *, field: str, min_val=None, max_val=None,
                   gt=None, lt=None):
    if isinstance(value, bool):
        err("ERR_VALIDATION", f"{field} must be a number.")
    if not isinstance(value, (int, float)):
        err("ERR_VALIDATION", f"{field} must be a number.")
    if min_val is not None and value < min_val:
        err("ERR_VALIDATION", f"{field} must be >= {min_val}.")
    if max_val is not None and value > max_val:
        err("ERR_VALIDATION", f"{field} must be <= {max_val}.")
    if gt is not None and not (value > gt):
        err("ERR_VALIDATION", f"{field} must be > {gt}.")
    if lt is not None and not (value < lt):
        err("ERR_VALIDATION", f"{field} must be < {lt}.")
    return value


def require_bool(value, *, field: str):
    if not isinstance(value, bool):
        err("ERR_VALIDATION", f"{field} must be a boolean.")
    return value


def require_iso(value, *, field: str):
    dt = parse_iso8601(value)
    if dt is None:
        err("ERR_VALIDATION", f"{field} must be an ISO 8601 UTC datetime.")
    return dt


def require_list(value, *, field: str, min_len=None):
    if not isinstance(value, list):
        err("ERR_VALIDATION", f"{field} must be an array.")
    if min_len is not None and len(value) < min_len:
        err("ERR_VALIDATION", f"{field} must have at least {min_len} elements.")
    return value


def get_pagination(args):
    """Parse limit/offset query parameters with default 10 / 0; min 1 / max 100."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "limit must be an integer 1..100.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err("ERR_VALIDATION", "offset must be a non-negative integer.")
    if limit < 1 or limit > 100:
        err("ERR_VALIDATION", "limit must be in 1..100.")
    if offset < 0:
        err("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
