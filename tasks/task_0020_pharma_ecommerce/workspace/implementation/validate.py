"""Lightweight input validation helpers."""

from __future__ import annotations

from typing import Any, Iterable

from errors import err


def require_json(body: Any) -> dict:
    if body is None:
        raise err("ERR_INVALID_REQUEST", "Missing JSON body.")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return body


def require_field(body: dict, field: str, *, kind: type | tuple = None):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field '{field}'.")
    val = body[field]
    if kind is not None and not isinstance(val, kind):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' has wrong type.")
    return val


def optional_field(body: dict, field: str, *, kind: type | tuple = None, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if kind is not None and not isinstance(val, kind):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' has wrong type.")
    return val


def require_enum(body: dict, field: str, allowed: Iterable[str]):
    val = require_field(body, field, kind=str)
    allowed_set = set(allowed)
    if val not in allowed_set:
        raise err(
            "ERR_INVALID_REQUEST",
            f"Field '{field}' must be one of {sorted(allowed_set)}.",
        )
    return val


def optional_enum(body: dict, field: str, allowed: Iterable[str], default=None):
    val = optional_field(body, field, kind=str, default=None)
    if val is None:
        return default
    if val not in set(allowed):
        raise err(
            "ERR_INVALID_REQUEST",
            f"Field '{field}' must be one of {sorted(set(allowed))}.",
        )
    return val


def require_pos_int(body: dict, field: str, *, min_val: int = 1):
    val = require_field(body, field, kind=int)
    if isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer.")
    if val < min_val:
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {min_val}.")
    return val


def require_str_array(body: dict, field: str, *, allow_empty: bool = True):
    val = body.get(field)
    if val is None:
        if not allow_empty:
            raise err("ERR_INVALID_REQUEST", f"Missing required field '{field}'.")
        return []
    if not isinstance(val, list):
        raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an array.")
    for item in val:
        if not isinstance(item, str):
            raise err("ERR_INVALID_REQUEST", f"Field '{field}' must be an array of strings.")
    return list(val)


def occ_check(body: dict, row: dict) -> None:
    """SCAFFOLD §1.2.1 + PRD §2.5 — optional `version` in body must match row."""
    if not isinstance(body, dict):
        return
    if "version" not in body or body["version"] is None:
        return
    if not isinstance(body["version"], int) or isinstance(body["version"], bool):
        raise err("ERR_INVALID_REQUEST", "Field 'version' must be an integer.")
    if int(body["version"]) != int(row.get("version", 0)):
        raise err("ERR_VERSION_MISMATCH", "Stale version supplied.")
