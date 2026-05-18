"""Tiny shared helpers used inside route modules."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from flask import request

from ..errors import APIError


def get_json_body() -> Dict[str, Any]:
    """Return the parsed JSON body as a dict (or {})."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but unparseable.
        raise APIError("ERR_INVALID_STATE", "Request body is not valid JSON", 409)
    if not isinstance(data, dict):
        raise APIError("ERR_INVALID_STATE", "Request body must be a JSON object", 409)
    return data


def require_field(body: Dict[str, Any], key: str) -> Any:
    if key not in body:
        raise APIError("ERR_INVALID_STATE", f"Missing required field '{key}'", 409)
    return body[key]


def as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise APIError("ERR_INVALID_STATE", f"'{field}' must be an integer", 409)
    if isinstance(value, int):
        return value
    raise APIError("ERR_INVALID_STATE", f"'{field}' must be an integer", 409)


def as_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise APIError("ERR_INVALID_STATE", f"'{field}' must be a number", 409)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            pass
    raise APIError("ERR_INVALID_STATE", f"'{field}' must be a number", 409)


def get_version(body: Dict[str, Any]) -> Optional[int]:
    if "version" not in body:
        return None
    v = body["version"]
    if not isinstance(v, int) or isinstance(v, bool):
        raise APIError("ERR_VERSION_CONFLICT", "version must be an integer", 409)
    return v
