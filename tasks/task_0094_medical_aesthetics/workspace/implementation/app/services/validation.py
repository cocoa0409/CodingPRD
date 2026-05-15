"""Shared validation helpers."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from ..clock import parse_iso, now_dt
from ..errors import ApiError


def require_keys(body: dict[str, Any], keys: list[str]) -> None:
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_INPUT", "Body must be a JSON object.")
    for k in keys:
        if k not in body:
            raise ApiError("ERR_INVALID_INPUT", f"Missing required field: {k}")


def require_str(value: Any, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_INPUT", f"{name} must be a string")
    if not allow_empty and value == "":
        raise ApiError("ERR_INVALID_INPUT", f"{name} must be non-empty")
    return value


def require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_INPUT", f"{name} must be an integer")
    return value


def require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_INPUT", f"{name} must be a boolean")
    return value


def check_occ(entity: dict[str, Any], body: dict[str, Any]) -> None:
    """Optional version-based OCC check."""
    if "version" in body and body["version"] is not None:
        try:
            req_v = int(body["version"])
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_INPUT", "version must be an integer")
        if req_v != int(entity.get("version", 0)):
            raise ApiError("ERR_VERSION_CONFLICT", "Stale version.")


def customer_age_at(dob_str: str, ref: datetime | None = None) -> int:
    ref = ref or now_dt()
    try:
        # Accept either date (YYYY-MM-DD) or datetime
        if "T" in dob_str:
            dob = parse_iso(dob_str)
            dob_d = dob.date()
        else:
            dob_d = date.fromisoformat(dob_str)
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", f"invalid date_of_birth: {dob_str!r}")
    ref_d = ref.date()
    years = ref_d.year - dob_d.year - ((ref_d.month, ref_d.day) < (dob_d.month, dob_d.day))
    return years
