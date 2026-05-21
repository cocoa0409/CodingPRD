"""Common helpers: required-field extraction, type coercion, body parsing."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from flask import request

from .errors import err_validation


def parse_json_body() -> dict:
    """Return JSON body as a dict, or {} for empty bodies. Reject non-object payloads."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise err_validation("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_validation("Request body must be a JSON object.")
    return body


def require_str(body: Mapping[str, Any], key: str) -> str:
    if key not in body or body[key] is None:
        raise err_validation(f"Required field missing: {key}.")
    val = body[key]
    if not isinstance(val, str) or not val.strip():
        raise err_validation(f"Field {key} must be a non-empty string.")
    return val


def require_int(body: Mapping[str, Any], key: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if key not in body or body[key] is None:
        raise err_validation(f"Required field missing: {key}.")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_validation(f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise err_validation(f"Field {key} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise err_validation(f"Field {key} must be <= {maximum}.")
    return val


def optional_int(body: Mapping[str, Any], key: str, *, default: int | None = 0, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err_validation(f"Field {key} must be an integer.")
    if minimum is not None and val < minimum:
        raise err_validation(f"Field {key} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise err_validation(f"Field {key} must be <= {maximum}.")
    return val


def require_enum(body: Mapping[str, Any], key: str, allowed: Iterable[str]) -> str:
    val = require_str(body, key)
    if val not in set(allowed):
        raise err_validation(f"Field {key} must be one of {sorted(allowed)}.")
    return val


def require_bool(body: Mapping[str, Any], key: str) -> bool:
    if key not in body or body[key] is None:
        raise err_validation(f"Required field missing: {key}.")
    val = body[key]
    if not isinstance(val, bool):
        raise err_validation(f"Field {key} must be a boolean.")
    return val


def optional_str(body: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise err_validation(f"Field {key} must be a string.")
    return val


def strip_internal(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}
