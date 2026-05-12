"""Common request validation helpers."""
from typing import Any
from flask import request

from errors import APIError, ERR_INVALID_REQUEST, raise_error


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "JSON body must be an object")
    return body


def require_field(body: dict, field: str):
    if field not in body or body[field] is None:
        raise_error(ERR_INVALID_REQUEST, f"missing field: {field}")
    return body[field]


def require_string(body: dict, field: str, min_len: int = 1, max_len: int | None = None):
    val = require_field(body, field)
    if not isinstance(val, str):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be string")
    if len(val) < min_len:
        raise_error(ERR_INVALID_REQUEST, f"field {field} too short")
    if max_len is not None and len(val) > max_len:
        raise_error(ERR_INVALID_REQUEST, f"field {field} too long")
    return val


def require_int(body: dict, field: str, min_v: int | None = None, max_v: int | None = None):
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be integer")
    if min_v is not None and val < min_v:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {min_v}")
    if max_v is not None and val > max_v:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {max_v}")
    return val


def optional_int(body: dict, field: str, min_v: int | None = None, max_v: int | None = None, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be integer")
    if min_v is not None and val < min_v:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {min_v}")
    if max_v is not None and val > max_v:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {max_v}")
    return val


def require_enum(body: dict, field: str, allowed: list[str]):
    val = require_field(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be one of {allowed}")
    return val


def optional_enum(body: dict, field: str, allowed: list[str], default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be one of {allowed}")
    return val


def require_list(body: dict, field: str):
    val = require_field(body, field)
    if not isinstance(val, list):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be array")
    return val


def optional_list(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default if default is not None else []
    val = body[field]
    if not isinstance(val, list):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be array")
    return val


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "invalid pagination parameters")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be 1..100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def check_optional_version(body: dict, entity: dict):
    """OCC: if version supplied and mismatches stored, raise ERR_INVALID_REQUEST."""
    if "version" in body and body["version"] is not None:
        v = body["version"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error(ERR_INVALID_REQUEST, "version must be integer")
        if v != entity.get("version"):
            raise_error(ERR_INVALID_REQUEST, "version mismatch")


def paginate_list(items: list, limit: int, offset: int) -> list:
    return items[offset: offset + limit]


def sort_by_created_at(items: list) -> list:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
