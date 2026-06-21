from __future__ import annotations

"""Body-level type / range validation helpers."""
import errors as E


def require_field(body: dict, field: str):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Required field missing: {field}")
    return body[field]


def require_string(body: dict, field: str, *, min_len: int = 1, max_len: int = None) -> str:
    val = require_field(body, field)
    if not isinstance(val, str):
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    if len(val) < min_len:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} too short")
    if max_len is not None and len(val) > max_len:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} too long")
    return val


def require_int(body: dict, field: str, *, min_val: int = None, max_val: int = None) -> int:
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if min_val is not None and val < min_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} below minimum {min_val}")
    if max_val is not None and val > max_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} above maximum {max_val}")
    return val


def require_number(body: dict, field: str, *, min_val: float = None, max_val: float = None) -> float:
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} must be a number")
    fval = float(val)
    if min_val is not None and fval < min_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} below minimum {min_val}")
    if max_val is not None and fval > max_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} above maximum {max_val}")
    return fval


def require_enum(body: dict, field: str, allowed: set[str]) -> str:
    val = require_field(body, field)
    if not isinstance(val, str) or val not in allowed:
        raise E.APIError(
            E.ERR_INVALID_REQUEST,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return val


def optional_string(body: dict, field: str, *, max_len: int = None) -> str | None:
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str):
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    if max_len is not None and len(val) > max_len:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} too long")
    return val


def optional_int(body: dict, field: str, *, min_val: int = None, max_val: int = None) -> int | None:
    if not isinstance(body, dict) or field not in body or body[field] is None:
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if min_val is not None and val < min_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} below minimum {min_val}")
    if max_val is not None and val > max_val:
        raise E.APIError(E.ERR_INVALID_REQUEST, f"Field {field} above maximum {max_val}")
    return val
