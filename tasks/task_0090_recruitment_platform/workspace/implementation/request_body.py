"""Request-body and query-parameter helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import request

from errors import ERR_VALIDATION, ERR_VERSION_CONFLICT, raise_err


def get_json_body() -> Dict[str, Any]:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_VALIDATION, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_VALIDATION, "Body must be a JSON object.")
    return body


def require_field(body: Dict[str, Any], field: str) -> Any:
    if field not in body or body[field] is None:
        raise_err(ERR_VALIDATION, f"Field '{field}' is required.")
    return body[field]


def maybe_field(body: Dict[str, Any], field: str, default=None):
    return body.get(field, default)


def check_version(body: Dict[str, Any], resource: Dict[str, Any]) -> None:
    """OCC check. Body version may be passed; query ?version also recognized."""
    v_query = request.args.get("version")
    v_body = body.get("version") if isinstance(body, dict) else None
    requested = v_body if v_body is not None else v_query
    if requested is None:
        return
    try:
        requested_int = int(requested)
    except (TypeError, ValueError):
        raise_err(ERR_VERSION_CONFLICT, "Invalid version value.")
    if requested_int != int(resource.get("version", 0)):
        raise_err(ERR_VERSION_CONFLICT, "Version mismatch.")


def parse_pagination() -> Tuple[int, int]:
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_str is not None:
        try:
            limit = int(limit_str)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset_str is not None:
        try:
            offset = int(offset_str)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer.")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be non-negative.")
    return limit, offset


def paginate(rows: list, limit: int, offset: int) -> Tuple[list, int]:
    total = len(rows)
    return rows[offset : offset + limit], total
