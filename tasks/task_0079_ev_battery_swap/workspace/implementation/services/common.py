"""Common helpers — common-field initialisation, version bumping, body parsing,
pagination, validation utilities, lookup helpers."""

from typing import Iterable

from flask import request

from db import DB
from errors import (
    ERR_INVALID_INPUT,
    ERR_INVALID_PAGINATION,
    ERR_NOT_FOUND,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from services.time_util import format_iso, server_now


def now_iso() -> str:
    return format_iso(server_now())


def init_common(row: dict) -> None:
    now = now_iso()
    row.setdefault("created_at", now)
    row.setdefault("updated_at", now)
    row.setdefault("version", 1)


def init_append_only(row: dict) -> None:
    row.setdefault("created_at", now_iso())


def bump_version(row: dict) -> None:
    row["version"] = int(row.get("version", 0)) + 1
    row["updated_at"] = now_iso()


def check_occ(row: dict, body) -> None:
    """If body contains 'version', compare to row['version']; mismatch -> 409."""
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    supplied = body.get("version")
    if supplied is None:
        return
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise_error(ERR_INVALID_INPUT, "version must be an integer")
    if supplied != int(row.get("version", 0)):
        raise_error(ERR_VERSION_CONFLICT, "version mismatch")


def get_or_404(table: str, oid: str) -> dict:
    row = DB[table].get(oid)
    if row is None:
        raise_error(ERR_NOT_FOUND, f"{table[:-1]} {oid} not found")
    return row


def get_or_none(table: str, oid: str):
    return DB[table].get(oid)


def get_body() -> dict:
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length and request.content_length > 0:
            try:
                body = request.get_json(silent=True)
            except Exception:
                body = None
            if body is None:
                return {}
            if not isinstance(body, dict):
                raise_error(ERR_INVALID_INPUT, "Body must be a JSON object")
            return body
        return {}
    return {}


def get_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_PAGINATION, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_PAGINATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_PAGINATION, "limit must be in [1, 100]")
    if offset < 0:
        raise_error(ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def sort_by_created_at_asc(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))


# ---- typed field accessors ---------------------------------------------------

def require_string(body, key, *, max_len=None, min_len=None):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_INPUT, f"{key} must be a non-empty string")
    if min_len is not None and len(v) < min_len:
        raise_error(ERR_INVALID_INPUT, f"{key} must be at least {min_len} characters")
    if max_len is not None and len(v) > max_len:
        raise_error(ERR_INVALID_INPUT, f"{key} must be at most {max_len} characters")
    return v


def optional_string(body, key, *, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_INPUT, f"{key} must be a string")
    return v


def require_number(body, key, *, allow_int=True):
    v = body.get(key)
    if isinstance(v, bool):
        raise_error(ERR_INVALID_INPUT, f"{key} must be a number")
    if isinstance(v, (int, float)):
        return float(v)
    raise_error(ERR_INVALID_INPUT, f"{key} must be a number")


def optional_number(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return require_number(body, key)


def require_int(body, key, *, min_value=None, max_value=None):
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_INVALID_INPUT, f"{key} must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_INVALID_INPUT, f"{key} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise_error(ERR_INVALID_INPUT, f"{key} must be <= {max_value}")
    return v


def optional_int(body, key, *, default=None, min_value=None, max_value=None):
    if key not in body or body.get(key) is None:
        return default
    return require_int(body, key, min_value=min_value, max_value=max_value)


def require_bool(body, key):
    v = body.get(key)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_INPUT, f"{key} must be a boolean")
    return v


def optional_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    return require_bool(body, key)


def require_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        raise_error(ERR_INVALID_INPUT, f"{key} must be one of {sorted(list(allowed))}")
    return v


def optional_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    return require_enum(body, key, allowed)
