"""Generic input validation helpers."""
from errors import err


def require_dict(body):
    if body is None:
        raise err("ERR_INVALID_INPUT", "Request body must be a JSON object")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_INPUT", "Request body must be a JSON object")
    return body


def required_str(body: dict, field: str) -> str:
    if field not in body:
        raise err("ERR_INVALID_INPUT", f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be a non-empty string")
    return val


def required_int(body: dict, field: str) -> int:
    if field not in body:
        raise err("ERR_INVALID_INPUT", f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be an integer")
    return val


def required_bool(body: dict, field: str) -> bool:
    if field not in body:
        raise err("ERR_INVALID_INPUT", f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be a boolean")
    return val


def optional_int(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be an integer")
    return val


def optional_bool(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be a boolean")
    return val


def in_range(value: int, low: int, high: int, field: str):
    if value < low or value > high:
        raise err("ERR_INVALID_INPUT", f"Field '{field}' out of bounds [{low},{high}]")


def at_least(value: int, low: int, field: str):
    if value < low:
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be >= {low}")


def must_uppercase(value: str, field: str):
    if not value.isupper() or any(c.isspace() for c in value):
        raise err("ERR_INVALID_INPUT", f"Field '{field}' must be uppercase")


def length_in(value: str, low: int, high: int, field: str):
    if len(value) < low or len(value) > high:
        raise err("ERR_INVALID_INPUT", f"Field '{field}' length must be in [{low},{high}]")
