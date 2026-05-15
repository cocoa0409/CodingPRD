"""Generic input validators used across routes."""
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from flask import request

from .errors import APIError


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise APIError("ERR_VALIDATION", "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError("ERR_VALIDATION", "request body must be a JSON object")
    return body


def require_field(body: dict, name: str) -> Any:
    if name not in body or body[name] is None:
        raise APIError("ERR_VALIDATION", f"missing required field '{name}'")
    return body[name]


def require_string(body: dict, name: str, *, min_len: int = 1, max_len: int = None,
                   pattern: str = None) -> str:
    value = require_field(body, name)
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", f"'{name}' must be a string")
    if len(value) < min_len:
        raise APIError("ERR_VALIDATION", f"'{name}' must be at least {min_len} chars")
    if max_len is not None and len(value) > max_len:
        raise APIError("ERR_VALIDATION", f"'{name}' must be at most {max_len} chars")
    if pattern is not None and not re.fullmatch(pattern, value):
        raise APIError("ERR_VALIDATION", f"'{name}' does not match required format")
    return value


def require_integer(body: dict, name: str, *, minimum: int = None, maximum: int = None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError("ERR_VALIDATION", f"'{name}' must be an integer")
    if minimum is not None and value < minimum:
        raise APIError("ERR_VALIDATION", f"'{name}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise APIError("ERR_VALIDATION", f"'{name}' must be <= {maximum}")
    return value


def require_number(body: dict, name: str, *, minimum=None, maximum=None,
                   max_decimals: int = None) -> float:
    value = require_field(body, name)
    if isinstance(value, bool):
        raise APIError("ERR_VALIDATION", f"'{name}' must be a number")
    if not isinstance(value, (int, float)):
        raise APIError("ERR_VALIDATION", f"'{name}' must be a number")
    fval = float(value)
    if minimum is not None and fval < float(minimum):
        raise APIError("ERR_VALIDATION", f"'{name}' must be >= {minimum}")
    if maximum is not None and fval > float(maximum):
        raise APIError("ERR_VALIDATION", f"'{name}' must be <= {maximum}")
    if max_decimals is not None:
        # Use string representation to count decimals robustly.
        try:
            dec = Decimal(str(value))
        except InvalidOperation:
            raise APIError("ERR_VALIDATION", f"'{name}' not a valid decimal")
        # number of decimal places
        exp = -dec.as_tuple().exponent
        if exp > max_decimals:
            raise APIError("ERR_VALIDATION", f"'{name}' must have at most {max_decimals} decimal places")
    return fval


def require_bool(body: dict, name: str) -> bool:
    value = require_field(body, name)
    if not isinstance(value, bool):
        raise APIError("ERR_VALIDATION", f"'{name}' must be a boolean")
    return value


def optional_field(body: dict, name: str, default=None):
    if name not in body:
        return default
    return body[name]


def parse_pagination():
    """Return (limit, offset) according to PRD §2.3 defaults; raise ERR_VALIDATION on invalid."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    try:
        limit = int(limit_s) if limit_s is not None else 10
    except ValueError:
        raise APIError("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(offset_s) if offset_s is not None else 0
    except ValueError:
        raise APIError("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise APIError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise APIError("ERR_VALIDATION", "offset must be non-negative")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset: offset + limit], total
