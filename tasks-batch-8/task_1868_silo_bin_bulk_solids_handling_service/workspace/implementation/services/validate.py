"""Request body structural validation helpers (PRD §2.10, priority 2)."""
from datetime import datetime

import errors
from db import parse_iso


def get_json_body() -> dict:
    if not request_body_present():
        return {}
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        raise errors.validation("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def request_body_present() -> bool:
    from flask import request
    return request.data is not None and len(request.data) > 0


def reject_unknown_fields(body: dict, allowed: set):
    unknown = set(body.keys()) - set(allowed)
    if unknown:
        raise errors.validation(f"Unknown fields: {sorted(unknown)}")


def require_fields(body: dict, required):
    for f in required:
        if f not in body or body[f] is None:
            raise errors.validation(f"Missing required field: {f}")


def as_string(value, field: str) -> str:
    if not isinstance(value, str):
        raise errors.validation(f"Field {field} must be a string")
    return value


def as_bool(value, field: str) -> bool:
    if not isinstance(value, bool):
        raise errors.validation(f"Field {field} must be a boolean")
    return value


def as_number(value, field: str):
    """int or float but not bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.validation(f"Field {field} must be a number")
    return value


def as_int(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.validation(f"Field {field} must be an integer")
    return value


def as_enum(value, field: str, allowed: set) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise errors.validation(f"Field {field} must be one of {sorted(allowed)}")
    return value


def as_iso8601(value, field: str) -> str:
    if not isinstance(value, str):
        raise errors.validation(f"Field {field} must be an ISO 8601 string")
    try:
        parse_iso(value)
    except Exception:
        raise errors.validation(f"Field {field} is not a valid ISO 8601 timestamp")
    return value


def check_range(value, field: str, min_v=None, max_v=None,
                min_exclusive=False, max_exclusive=False):
    from decimal import Decimal
    d = Decimal(str(value))
    if min_v is not None:
        if min_exclusive and not (d > Decimal(str(min_v))):
            raise errors.validation(f"Field {field} must be > {min_v}")
        if not min_exclusive and not (d >= Decimal(str(min_v))):
            raise errors.validation(f"Field {field} must be >= {min_v}")
    if max_v is not None:
        if max_exclusive and not (d < Decimal(str(max_v))):
            raise errors.validation(f"Field {field} must be < {max_v}")
        if not max_exclusive and not (d <= Decimal(str(max_v))):
            raise errors.validation(f"Field {field} must be <= {max_v}")


def parse_pagination():
    """Read limit/offset per SCAFFOLD §1.0 pagination_defaults: limit 10, min 1, max 100, offset 0."""
    from flask import request
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit out of range (1..100)")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")

    return limit, offset
