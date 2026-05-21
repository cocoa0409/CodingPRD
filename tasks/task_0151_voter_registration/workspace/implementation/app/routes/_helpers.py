"""Tiny shared helpers used inside route modules."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import request

from ..errors import APIError, err_bad_request, err_version_mismatch


def get_json_body() -> Dict[str, Any]:
    """Return the parsed JSON body as a dict (or {} if no body)."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err_bad_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err_bad_request("Request body must be a JSON object")
    return data


def require_field(body: Dict[str, Any], key: str) -> Any:
    if key not in body:
        raise err_bad_request(f"Missing required field '{key}'")
    return body[key]


def as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise err_bad_request(f"'{field}' must be an integer")
    if isinstance(value, int):
        return value
    raise err_bad_request(f"'{field}' must be an integer")


def as_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise err_bad_request(f"'{field}' must be a string")
    return value


def as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise err_bad_request(f"'{field}' must be a boolean")
    return value


def get_version(body: Dict[str, Any]) -> Optional[int]:
    """OCC: return supplied version (int) or None when omitted."""
    if "version" not in body:
        return None
    v = body["version"]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_version_mismatch("version must be an integer")
    return v
