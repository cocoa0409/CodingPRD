"""Payload validation helpers."""
from __future__ import annotations

from typing import Any, Iterable

from errors import InvalidRequest


def require_fields(payload: dict, fields: Iterable[str]) -> None:
    if not isinstance(payload, dict):
        raise InvalidRequest("payload must be a JSON object")
    for f in fields:
        if f not in payload:
            raise InvalidRequest(f"missing required field: {f}")


def as_str(payload: dict, field: str, *, required: bool = True) -> str | None:
    if field not in payload:
        if required:
            raise InvalidRequest(f"missing required field: {field}")
        return None
    val = payload[field]
    if not isinstance(val, str):
        raise InvalidRequest(f"{field} must be a string")
    return val


def as_int(payload: dict, field: str, *, required: bool = True) -> int | None:
    if field not in payload:
        if required:
            raise InvalidRequest(f"missing required field: {field}")
        return None
    val = payload[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise InvalidRequest(f"{field} must be an integer")
    return val


def as_number(payload: dict, field: str, *, required: bool = True) -> float | None:
    if field not in payload:
        if required:
            raise InvalidRequest(f"missing required field: {field}")
        return None
    val = payload[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidRequest(f"{field} must be a number")
    return float(val)


def as_bool(payload: dict, field: str, *, default: bool = False, required: bool = False) -> bool:
    if field not in payload:
        if required:
            raise InvalidRequest(f"missing required field: {field}")
        return default
    val = payload[field]
    if not isinstance(val, bool):
        raise InvalidRequest(f"{field} must be a boolean")
    return val


def as_enum(payload: dict, field: str, allowed: set[str], *, required: bool = True) -> str | None:
    val = as_str(payload, field, required=required)
    if val is None:
        return None
    if val not in allowed:
        raise InvalidRequest(f"{field} must be one of {sorted(allowed)}")
    return val


def as_list(payload: dict, field: str, *, required: bool = True) -> list | None:
    if field not in payload:
        if required:
            raise InvalidRequest(f"missing required field: {field}")
        return None
    val = payload[field]
    if not isinstance(val, list):
        raise InvalidRequest(f"{field} must be a list")
    return val
