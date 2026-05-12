"""Schema-level validation helpers (PRD §2.8 priority 20)."""

from __future__ import annotations

from typing import Any, Iterable

from flask import request

from errors import err


def get_json_body() -> dict:
    """Read the JSON body. An absent or non-dict body becomes ERR_VALIDATION."""
    if request.method in ("GET", "DELETE"):
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        raise err("ERR_VALIDATION", "Malformed JSON body.")
    if body is None:
        # Treat empty body as empty dict (some endpoints take no input)
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Body must be a JSON object.")
    return body


def require_fields(body: dict, fields: Iterable[str]) -> None:
    for f in fields:
        if f not in body or body.get(f) in (None, ""):
            raise err("ERR_VALIDATION", f"Missing required field '{f}'.")


def require_enum(value: Any, allowed: Iterable[str], field: str) -> None:
    if value not in set(allowed):
        raise err(
            "ERR_VALIDATION",
            f"Field '{field}' must be one of {sorted(set(allowed))}; got {value!r}.",
        )


def require_int(value: Any, field: str, *, min_value: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", f"Field '{field}' must be an integer.")
    if min_value is not None and value < min_value:
        raise err("ERR_VALIDATION", f"Field '{field}' must be >= {min_value}.")
    return value


def require_number(value: Any, field: str, *, min_value: float | None = None,
                   max_value: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_VALIDATION", f"Field '{field}' must be a number.")
    if min_value is not None and value < min_value:
        raise err("ERR_VALIDATION", f"Field '{field}' must be >= {min_value}.")
    if max_value is not None and value > max_value:
        raise err("ERR_VALIDATION", f"Field '{field}' must be <= {max_value}.")
    return float(value)


def require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", f"Field '{field}' must be a string.")
    if not allow_empty and value.strip() == "":
        raise err("ERR_VALIDATION", f"Field '{field}' must be non-empty.")
    return value


def require_list(value: Any, field: str, *, allow_empty: bool = True) -> list:
    if not isinstance(value, list):
        raise err("ERR_VALIDATION", f"Field '{field}' must be a list.")
    if not allow_empty and len(value) == 0:
        raise err("ERR_VALIDATION", f"Field '{field}' must be non-empty.")
    return value
