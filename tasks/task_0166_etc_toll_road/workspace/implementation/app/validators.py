"""Field-level validators for request payloads."""
from typing import Any, Iterable

from .errors import ApiError


AGENCIES = {"NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"}
PLATE_STATES = {"NY", "NJ", "PA", "FL", "CA", "TX", "OTHER"}


def require_json(payload: Any) -> dict:
    if payload is None or not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return payload


def require(payload: dict, field: str) -> Any:
    if field not in payload or payload[field] is None:
        raise ApiError("ERR_VALIDATION", 422, f"Missing required field: {field}")
    return payload[field]


def require_str(payload: dict, field: str, min_len: int = 1, max_len: int = 1024) -> str:
    val = require(payload, field)
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a string.")
    if len(val) < min_len or len(val) > max_len:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} length out of range.")
    return val


def optional_str(payload: dict, field: str, default=None, min_len: int = 1, max_len: int = 1024):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, str):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a string.")
    if len(val) < min_len or len(val) > max_len:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} length out of range.")
    return val


def require_int(payload: dict, field: str, lo: int, hi: int) -> int:
    val = require(payload, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer.")
    if val < lo or val > hi:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be between {lo} and {hi}.")
    return val


def optional_int(payload: dict, field: str, lo: int, hi: int, default=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be an integer.")
    if val < lo or val > hi:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be between {lo} and {hi}.")
    return val


def require_enum(payload: dict, field: str, allowed: Iterable[str]) -> str:
    val = require_str(payload, field, min_len=1, max_len=64)
    if val not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be one of: {sorted(set(allowed))}")
    return val


def optional_enum(payload: dict, field: str, allowed: Iterable[str], default=None):
    if field not in payload or payload[field] is None:
        return default
    return require_enum(payload, field, allowed)


def optional_bool(payload: dict, field: str, default=None):
    if field not in payload or payload[field] is None:
        return default
    val = payload[field]
    if not isinstance(val, bool):
        raise ApiError("ERR_VALIDATION", 422, f"Field {field} must be a boolean.")
    return val


def normalize_plate(plate: str) -> str:
    p = plate.strip().upper().replace(" ", "")
    if len(p) < 1 or len(p) > 10:
        raise ApiError("ERR_VALIDATION", 422, "plate_number must be 1..10 characters.")
    for c in p:
        if not (c.isalnum() or c == "-"):
            raise ApiError("ERR_VALIDATION", 422, "plate_number contains invalid characters.")
    return p


def normalize_serial(serial: str) -> str:
    s = serial.strip().upper()
    if len(s) < 10 or len(s) > 24:
        raise ApiError("ERR_VALIDATION", 422, "serial_number must be 10..24 characters.")
    for c in s:
        if not c.isalnum():
            raise ApiError("ERR_VALIDATION", 422, "serial_number must be alphanumeric uppercase.")
    return s
