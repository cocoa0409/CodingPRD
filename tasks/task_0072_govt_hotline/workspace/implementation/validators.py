"""Field-shape validators. All raise ERR_VALIDATION on failure."""

import re
from typing import Any

from errors import AppError, ERR_VALIDATION, ERROR_STATUS


def _fail(msg: str):
    raise AppError(ERR_VALIDATION, msg, ERROR_STATUS[ERR_VALIDATION])


def require_present(body: dict, key: str):
    if key not in body or body[key] is None:
        _fail(f"{key} is required")


def is_str(body: dict, key: str, *, min_len: int = None, max_len: int = None, pattern: str = None,
           optional: bool = False, allow_empty: bool = False):
    if key not in body or body[key] is None:
        if optional:
            return None
        _fail(f"{key} is required")
    v = body[key]
    if not isinstance(v, str):
        _fail(f"{key} must be a string")
    if not allow_empty and v == "" and (min_len is None or min_len > 0):
        _fail(f"{key} must be a non-empty string")
    if min_len is not None and len(v) < min_len:
        _fail(f"{key} must be at least {min_len} characters")
    if max_len is not None and len(v) > max_len:
        _fail(f"{key} must be at most {max_len} characters")
    if pattern is not None and not re.fullmatch(pattern, v):
        _fail(f"{key} does not match required pattern")
    return v


def is_int(body: dict, key: str, *, min_v: int = None, max_v: int = None, optional: bool = False, default=None):
    if key not in body or body[key] is None:
        if optional:
            return default
        _fail(f"{key} is required")
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"{key} must be an integer")
    if min_v is not None and v < min_v:
        _fail(f"{key} must be >= {min_v}")
    if max_v is not None and v > max_v:
        _fail(f"{key} must be <= {max_v}")
    return v


def is_bool(body: dict, key: str, *, optional: bool = False, default: bool = None):
    if key not in body or body[key] is None:
        if optional:
            return default
        _fail(f"{key} is required")
    v = body[key]
    if not isinstance(v, bool):
        _fail(f"{key} must be boolean")
    return v


def is_enum(body: dict, key: str, allowed, *, optional: bool = False, default=None):
    if key not in body or body[key] is None:
        if optional:
            return default
        _fail(f"{key} is required")
    v = body[key]
    if v not in allowed:
        _fail(f"{key} must be one of {sorted(allowed)}")
    return v


def is_list(body: dict, key: str, *, optional: bool = False, default=None):
    if key not in body or body[key] is None:
        if optional:
            return default if default is not None else []
        _fail(f"{key} is required")
    v = body[key]
    if not isinstance(v, list):
        _fail(f"{key} must be a list")
    return v


JURISDICTION_RE = r"J[0-9]{4}"
DEPT_CODE_RE = r"[a-z][a-z0-9-]{1,39}"
CATEGORY_RE = r"[A-Z][A-Z0-9_]{1,29}"
PHONE_RE = r"[0-9+\-]{6,20}"
URL_RE = r"(https?://.+|)"
