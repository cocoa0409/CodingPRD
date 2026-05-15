"""Generic input-shape validation helpers."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from flask import request

from app.errors import make_error
from app.numeric import to_decimal


def get_json_body() -> dict[str, Any]:
    """Accept a JSON object body or empty body; reject malformed JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise make_error("ERR_VALIDATION", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise make_error("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_field(body: dict, name: str, *, error_id: str = "ERR_VALIDATION") -> Any:
    if name not in body or body[name] is None:
        raise make_error(error_id, f"Missing required field: {name}")
    return body[name]


def require_str(body: dict, name: str, *, max_len: Optional[int] = None,
                min_len: int = 1, error_id: str = "ERR_VALIDATION") -> str:
    value = require_field(body, name, error_id=error_id)
    if not isinstance(value, str):
        raise make_error(error_id, f"Field {name} must be a string.")
    if len(value) < min_len:
        raise make_error(error_id, f"Field {name} is too short.")
    if max_len is not None and len(value) > max_len:
        raise make_error(error_id, f"Field {name} is too long.")
    return value


def require_decimal(body: dict, name: str, *, gt: Optional[Decimal] = None,
                    gte: Optional[Decimal] = None,
                    error_id: str = "ERR_VALIDATION") -> Decimal:
    raw = require_field(body, name, error_id=error_id)
    try:
        value = to_decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise make_error(error_id, f"Field {name} must be numeric.")
    if gt is not None and not value > gt:
        raise make_error(error_id, f"Field {name} must be greater than {gt}.")
    if gte is not None and not value >= gte:
        raise make_error(error_id, f"Field {name} must be >= {gte}.")
    return value


def require_int(body: dict, name: str, *, lo: Optional[int] = None,
                hi: Optional[int] = None, error_id: str = "ERR_VALIDATION") -> int:
    raw = require_field(body, name, error_id=error_id)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise make_error(error_id, f"Field {name} must be an integer.")
    if lo is not None and raw < lo:
        raise make_error(error_id, f"Field {name} must be >= {lo}.")
    if hi is not None and raw > hi:
        raise make_error(error_id, f"Field {name} must be <= {hi}.")
    return raw


def require_enum(body: dict, name: str, options: set[str], *,
                 error_id: str = "ERR_VALIDATION") -> str:
    value = require_field(body, name, error_id=error_id)
    if value not in options:
        raise make_error(
            error_id,
            f"Field {name} must be one of {sorted(options)}.",
        )
    return value


def optional_decimal(body: dict, name: str, *, gt: Optional[Decimal] = None,
                     gte: Optional[Decimal] = None,
                     error_id: str = "ERR_VALIDATION") -> Optional[Decimal]:
    if name not in body or body[name] is None:
        return None
    try:
        value = to_decimal(body[name])
    except (InvalidOperation, TypeError, ValueError):
        raise make_error(error_id, f"Field {name} must be numeric.")
    if gt is not None and not value > gt:
        raise make_error(error_id, f"Field {name} must be greater than {gt}.")
    if gte is not None and not value >= gte:
        raise make_error(error_id, f"Field {name} must be >= {gte}.")
    return value


def parse_pagination() -> tuple[int, int]:
    """Read `limit` and `offset` query parameters; validate per §2.3."""
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise make_error("ERR_INVALID_PAGINATION")
    if limit < 1 or limit > 100 or offset < 0:
        raise make_error("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows: list[dict], limit: int, offset: int) -> tuple[list[dict], int]:
    """Sort by created_at then id ascending, then slice."""
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.get("created_at", ""), r.get("id", "")),
    )
    total = len(sorted_rows)
    page = sorted_rows[offset:offset + limit]
    return page, total


def check_version(body: dict, current_version: int) -> None:
    """OCC check — only when caller supplies a version field."""
    if "version" not in body or body["version"] is None:
        return
    if body["version"] != current_version:
        raise make_error("ERR_VERSION_CONFLICT")
