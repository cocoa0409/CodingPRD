"""Input parsing/validation helpers."""
from __future__ import annotations

from typing import Any

from flask import request

from .envelope import err_validation


def get_json(required: bool = True) -> dict:
    try:
        data = request.get_json(silent=True)
    except Exception:
        raise err_validation("Malformed JSON body")
    if data is None:
        if required:
            raise err_validation("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def require_str(d: dict, key: str, *, max_len: int | None = None, allow_empty: bool = False) -> str:
    v = d.get(key)
    if not isinstance(v, str):
        raise err_validation(f"Field '{key}' must be a string")
    if not allow_empty and not v:
        raise err_validation(f"Field '{key}' must not be empty")
    if max_len is not None and len(v) > max_len:
        raise err_validation(f"Field '{key}' is too long")
    return v


def require_int(d: dict, key: str, *, minv: int | None = None, maxv: int | None = None) -> int:
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_validation(f"Field '{key}' must be an integer")
    if minv is not None and v < minv:
        raise err_validation(f"Field '{key}' must be >= {minv}")
    if maxv is not None and v > maxv:
        raise err_validation(f"Field '{key}' must be <= {maxv}")
    return v


def require_number(d: dict, key: str, *, minv: float | None = None, maxv: float | None = None) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation(f"Field '{key}' must be a number")
    f = float(v)
    if minv is not None and f < minv:
        raise err_validation(f"Field '{key}' must be >= {minv}")
    if maxv is not None and f > maxv:
        raise err_validation(f"Field '{key}' must be <= {maxv}")
    return f


def optional_str(d: dict, key: str, *, max_len: int | None = None) -> str | None:
    if key not in d or d[key] is None:
        return None
    return require_str(d, key, max_len=max_len)


def optional_int(d: dict, key: str, *, minv: int | None = None, maxv: int | None = None) -> int | None:
    if key not in d or d[key] is None:
        return None
    return require_int(d, key, minv=minv, maxv=maxv)


def optional_number(d: dict, key: str, *, minv: float | None = None, maxv: float | None = None) -> float | None:
    if key not in d or d[key] is None:
        return None
    return require_number(d, key, minv=minv, maxv=maxv)


def pagination_params() -> tuple[int, int]:
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except ValueError:
        raise err_validation("limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise err_validation("limit must be between 1 and 100")
    if offset < 0:
        raise err_validation("offset must be >= 0")
    return limit, offset
