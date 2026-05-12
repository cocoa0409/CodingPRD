"""Common request-body / field validation helpers."""

from __future__ import annotations

from typing import Any

from errors import AppError, ERR_VALIDATION_FAILED


def must_be_dict(body: Any) -> dict:
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AppError(ERR_VALIDATION_FAILED, "request body must be JSON object", 422)
    return body


def require_field(body: dict, name: str) -> Any:
    if name not in body or body[name] is None:
        raise AppError(ERR_VALIDATION_FAILED, f"missing required field: {name}", 422)
    return body[name]


def require_str(body: dict, name: str, *, min_len: int | None = None,
                max_len: int | None = None) -> str:
    value = require_field(body, name)
    if not isinstance(value, str):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be a string", 422)
    if min_len is not None and len(value) < min_len:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"{name} must be at least {min_len} chars", 422)
    if max_len is not None and len(value) > max_len:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"{name} must be at most {max_len} chars", 422)
    return value


def opt_str(body: dict, name: str, default=None) -> str | None:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be a string", 422)
    return value


def require_int(body: dict, name: str, *, min_value: int | None = None,
                max_value: int | None = None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be an integer", 422)
    if min_value is not None and value < min_value:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"{name} must be >= {min_value}", 422)
    if max_value is not None and value > max_value:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"{name} must be <= {max_value}", 422)
    return value


def opt_int(body: dict, name: str, default=None, *, min_value=None, max_value=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be an integer", 422)
    if min_value is not None and value < min_value:
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be >= {min_value}", 422)
    if max_value is not None and value > max_value:
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be <= {max_value}", 422)
    return value


def require_enum(body: dict, name: str, allowed: set[str]) -> str:
    value = require_str(body, name)
    if value not in allowed:
        raise AppError(ERR_VALIDATION_FAILED,
                       f"{name} must be one of {sorted(allowed)}", 422)
    return value


def require_list(body: dict, name: str, *, non_empty: bool = False) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be an array", 422)
    if non_empty and len(value) == 0:
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be non-empty", 422)
    return value


def require_dict_field(body: dict, name: str) -> dict:
    value = require_field(body, name)
    if not isinstance(value, dict):
        raise AppError(ERR_VALIDATION_FAILED, f"{name} must be an object", 422)
    return value
