"""Small validation/parsing helpers shared across routes."""
from __future__ import annotations

import re
import uuid
from typing import Any

from flask import request

from .errors import APIError, err_invalid_input


STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
EIN_RE = re.compile(r"^[0-9]{2}-[0-9]{7}$")
SSN4_RE = re.compile(r"^[0-9]{4}$")
PO_BOX_RE = re.compile(r"^P\.?O\.? Box", re.IGNORECASE)


def new_uuid() -> str:
    return str(uuid.uuid4())


def get_json_body() -> dict[str, Any]:
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # An empty body is treated as an empty object — many of our POST action
        # endpoints accept zero-input bodies.
        if not request.data:
            return {}
        raise err_invalid_input("Body must be valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_input("Body must be a JSON object")
    return data


def require_field(body: dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        raise err_invalid_input(f"Missing required field: {field}")
    return body[field]


def require_str(body: dict[str, Any], field: str, *, min_len: int = 1, max_len: int | None = None) -> str:
    val = require_field(body, field)
    if not isinstance(val, str):
        raise err_invalid_input(f"Field '{field}' must be a string")
    if len(val) < min_len:
        raise err_invalid_input(f"Field '{field}' must be at least {min_len} character(s)")
    if max_len is not None and len(val) > max_len:
        raise err_invalid_input(f"Field '{field}' exceeds maximum length {max_len}")
    return val


def require_state_code(body: dict[str, Any], field: str) -> str:
    val = require_str(body, field, min_len=2, max_len=2)
    if not STATE_CODE_RE.match(val):
        raise err_invalid_input(f"Field '{field}' must match ^[A-Z]{{2}}$")
    return val


def require_int(body: dict[str, Any], field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_invalid_input(f"Field '{field}' must be an integer")
    if minimum is not None and val < minimum:
        raise err_invalid_input(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err_invalid_input(f"Field '{field}' must be <= {maximum}")
    return val


def optional_int(body: dict[str, Any], field: str, *, minimum: int | None = None, maximum: int | None = None, default: int | None = None) -> int | None:
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_invalid_input(f"Field '{field}' must be an integer")
    if minimum is not None and val < minimum:
        raise err_invalid_input(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err_invalid_input(f"Field '{field}' must be <= {maximum}")
    return val


def optional_str(body: dict[str, Any], field: str, *, min_len: int = 1, max_len: int | None = None) -> str | None:
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str):
        raise err_invalid_input(f"Field '{field}' must be a string")
    if len(val) < min_len:
        raise err_invalid_input(f"Field '{field}' must be at least {min_len} character(s)")
    if max_len is not None and len(val) > max_len:
        raise err_invalid_input(f"Field '{field}' exceeds maximum length {max_len}")
    return val


def require_enum(body: dict[str, Any], field: str, values: set[str]) -> str:
    val = require_str(body, field)
    if val not in values:
        raise err_invalid_input(f"Field '{field}' must be one of {sorted(values)}")
    return val


def optional_enum(body: dict[str, Any], field: str, values: set[str]) -> str | None:
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str) or val not in values:
        raise err_invalid_input(f"Field '{field}' must be one of {sorted(values)}")
    return val


def parse_pagination() -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err_invalid_input("Query parameter 'limit' must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err_invalid_input("Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_input("Query parameter 'limit' must be in [1, 100]")
    if offset < 0:
        raise err_invalid_input("Query parameter 'offset' must be >= 0")
    return limit, offset
