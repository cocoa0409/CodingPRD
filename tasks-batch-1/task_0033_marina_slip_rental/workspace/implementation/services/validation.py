"""Reusable validation helpers — surface ERR_INVALID_REQUEST (HTTP 400).

These are the lowest-priority validations per PRD §2.7. Higher-priority
validations (auth/existence/state/business) live in route or service modules
and are checked before falling through to these.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, Optional

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---- primitive type/range checks --------------------------------------------


def require_fields(body: Dict[str, Any], fields: Iterable[str]) -> None:
    for f in fields:
        if f not in body or body[f] is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Required field missing: {f}")


def require_string(value: Any, field_name: str, *, max_len: Optional[int] = None,
                   min_len: int = 1) -> str:
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a string")
    if len(value) < min_len:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{field_name} must be at least {min_len} characters")
    if max_len is not None and len(value) > max_len:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"{field_name} must be at most {max_len} characters")
    return value


def require_enum(value: Any, choices: Iterable[str], field_name: str) -> str:
    if value not in choices:
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"Invalid value for {field_name}: {value!r}",
        )
    return value


def require_int(
    value: Any,
    field_name: str,
    *,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be an integer")
    if min_value is not None and value < min_value:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be >= {min_value}"
        )
    if max_value is not None and value > max_value:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be <= {max_value}"
        )
    return value


def require_number(
    value: Any,
    field_name: str,
    *,
    min_value: Optional[float] = None,
    strict_min: Optional[float] = None,
) -> float:
    """Accept int or float (but not bool). Returns float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a number")
    v = float(value)
    if min_value is not None and v < min_value:
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be >= {min_value}")
    if strict_min is not None and not (v > strict_min):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be > {strict_min}")
    return v


def require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, 400, f"{field_name} must be a boolean")
    return value


# ---- date / datetime helpers ------------------------------------------------


def require_date(value: Any, field_name: str) -> date:
    try:
        d = db.parse_iso_date(value)
    except (ValueError, TypeError):
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a YYYY-MM-DD date"
        )
    if d is None:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a YYYY-MM-DD date"
        )
    return d


def require_mmdd(value: Any, field_name: str) -> tuple:
    try:
        m = db.parse_mmdd(value)
    except (ValueError, TypeError):
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a MM-DD calendar fragment"
        )
    if m is None:
        raise APIError(
            ERR_INVALID_REQUEST, 400, f"{field_name} must be a MM-DD calendar fragment"
        )
    return m


# ---- formatted-string constraints ------------------------------------------


_HARBOR_RE = re.compile(r"^[A-Z]{3}$")


def require_harbor_code(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _HARBOR_RE.match(value):
        raise APIError(
            ERR_INVALID_REQUEST,
            400,
            f"{field_name} must be three uppercase letters",
        )
    return value


# ---- FK / existence helpers -------------------------------------------------


def lookup_or_404(
    store: Dict[str, Dict[str, Any]], rid: Optional[str], kind: str
) -> Dict[str, Any]:
    """Raise ERR_NOT_FOUND (404) when id is missing or absent.

    Used for both path-segment existence (PRD §2.5) and body-FK existence.
    """
    if not isinstance(rid, str) or not rid:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid!r}")
    obj = store.get(rid)
    if obj is None:
        raise APIError(ERR_NOT_FOUND, 404, f"{kind} not found: {rid}")
    return obj
