"""Shared request-shape validation helpers."""

from __future__ import annotations

from typing import Any

from errors import invalid_request


def require_object(body: Any) -> dict:
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def reject_unknown_fields(body: dict, allowed: set[str]) -> None:
    unknown = set(body.keys()) - allowed
    if unknown:
        raise invalid_request(f"Unknown fields: {sorted(unknown)}")


def require_fields(body: dict, required: list[str]) -> None:
    for f in required:
        if f not in body:
            raise invalid_request(f"Missing required field: {f}")


def req_str(body: dict, field: str, *, allow_empty: bool = True) -> str:
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    if not allow_empty and not v:
        raise invalid_request(f"Field {field} must be non-empty")
    return v


def opt_str(body: dict, field: str) -> str | None:
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string")
    return v


def req_num(body: dict, field: str) -> float:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {field} must be a number")
    return v


def req_int(body: dict, field: str) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {field} must be an integer")
    return v


def req_bool(body: dict, field: str) -> bool:
    v = body.get(field)
    if not isinstance(v, bool):
        raise invalid_request(f"Field {field} must be a boolean")
    return v


def req_enum(body: dict, field: str, allowed: set[str]) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_list(body: dict, field: str) -> list:
    v = body.get(field)
    if not isinstance(v, list):
        raise invalid_request(f"Field {field} must be an array")
    return v


def req_str_list(body: dict, field: str) -> list[str]:
    v = req_list(body, field)
    for item in v:
        if not isinstance(item, str):
            raise invalid_request(f"Field {field} must be an array of strings")
    return v
