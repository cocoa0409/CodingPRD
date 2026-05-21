"""Body parsing + common shape validation helpers.

All validation failures here raise APIError with error_id ERR_VALIDATION (422)
unless a more specific error applies.
"""
from __future__ import annotations

from typing import Any

from flask import request

from .errors import raise_error
from .time_utils import parse_iso


def get_json_body() -> dict:
    """Return the JSON body or an empty dict if none was supplied.

    A malformed JSON payload raises ERR_VALIDATION.
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_VALIDATION", "Body is not valid JSON.")
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Body must be a JSON object.")
    return body


def require_fields(body: dict, fields: list[str]) -> None:
    missing = [f for f in fields if f not in body or body[f] is None]
    if missing:
        raise_error("ERR_VALIDATION", f"Missing required field(s): {', '.join(missing)}")


def as_string(value: Any, field: str, min_len: int = 1, max_len: int | None = None) -> str:
    if not isinstance(value, str):
        raise_error("ERR_VALIDATION", f"Field '{field}' must be a string.")
    if len(value) < min_len:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be at least {min_len} chars.")
    if max_len is not None and len(value) > max_len:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be at most {max_len} chars.")
    return value


def as_int(value: Any, field: str, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_VALIDATION", f"Field '{field}' must be an integer.")
    if minimum is not None and value < minimum:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be <= {maximum}.")
    return value


def as_number(value: Any, field: str, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error("ERR_VALIDATION", f"Field '{field}' must be a number.")
    f = float(value)
    if minimum is not None and f < minimum:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be >= {minimum}.")
    if maximum is not None and f > maximum:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be <= {maximum}.")
    return f


def as_enum(value: Any, field: str, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise_error("ERR_VALIDATION", f"Field '{field}' must be one of {sorted(choices)}.")
    return value


def as_iso_datetime(value: Any, field: str):
    if not isinstance(value, str):
        raise_error("ERR_VALIDATION", f"Field '{field}' must be an ISO 8601 string.")
    try:
        return parse_iso(value)
    except Exception:
        raise_error("ERR_VALIDATION", f"Field '{field}' is not a valid ISO 8601 timestamp.")


def as_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise_error("ERR_VALIDATION", f"Field '{field}' must be a boolean.")
    return value


def parse_pagination() -> tuple[int, int]:
    """Read limit/offset query args with PRD defaults (10/0, max 100)."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_error("ERR_VALIDATION", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise_error("ERR_VALIDATION", "limit must be in [1, 100].")
    if offset < 0:
        raise_error("ERR_VALIDATION", "offset must be >= 0.")
    return limit, offset


def check_version_if_supplied(entity: dict, body: dict) -> None:
    """OCC check: if body['version'] is present, compare against entity['version']."""
    if "version" not in body or body["version"] is None:
        return
    supplied = body["version"]
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise_error("ERR_VALIDATION", "version must be an integer.")
    if int(supplied) != int(entity.get("version", 0)):
        raise_error("ERR_VERSION_CONFLICT")
