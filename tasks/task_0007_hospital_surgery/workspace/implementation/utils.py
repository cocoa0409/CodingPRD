from flask import request

from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_TIME_PARAMETERS,
    ERR_STALE_DATA,
)


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_int_query(name: str, default: int) -> int:
    val = request.args.get(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"Query param '{name}' must be an integer")


def get_pagination():
    limit = parse_int_query("limit", 10)
    offset = parse_int_query("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def require_int(body: dict, key: str, *, allow_zero=True, allow_negative=False) -> int:
    if key not in body or body[key] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field '{key}'")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be an integer")
    if not allow_negative and val < 0:
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-negative")
    if not allow_zero and val == 0:
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-zero")
    return val


def require_str(body: dict, key: str) -> str:
    if key not in body or body[key] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field '{key}'")
    val = body[key]
    if not isinstance(val, str) or not val.strip():
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be a non-empty string")
    return val


def optional_str(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be a string")
    return val


def optional_bool(body: dict, key: str, default=False) -> bool:
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be a boolean")
    return val


def require_number(body: dict, key: str, *, allow_negative=False):
    if key not in body or body[key] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field '{key}'")
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be a number")
    if not allow_negative and val < 0:
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-negative")
    return val


def optional_number(body: dict, key: str, default=None, *, allow_negative=False):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be a number")
    if not allow_negative and val < 0:
        raise_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-negative")
    return val


def check_version(body: dict, entity: dict):
    """If version provided in body, verify it matches; raise ERR_STALE_DATA otherwise."""
    if "version" not in body or body["version"] is None:
        return
    val = body["version"]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_REQUEST, "Field 'version' must be an integer")
    if val != entity.get("version"):
        raise_error(ERR_STALE_DATA, "version mismatch")
