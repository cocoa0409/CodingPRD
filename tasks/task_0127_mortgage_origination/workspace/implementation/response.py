"""Response envelope builders (PRD §2.2, §2.3; SCAFFOLD response_envelope)."""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from config import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import AppError, ERR_VALIDATION, ERROR_STATUS


_REQ_ID_ALPHABET = string.ascii_letters + string.digits


def _request_id() -> str:
    suffix = "".join(secrets.choice(_REQ_ID_ALPHABET) for _ in range(20))
    return f"req_{suffix}"


def _now_iso() -> str:
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _meta() -> dict:
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def success(data, status_code: int = 200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status_code


def success_list(items, total_count: int, limit: int, offset: int):
    meta = _meta()
    meta.update(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id: str, message: str, status_code: int):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code


def parse_pagination(args):
    """Extract limit/offset from query args, clamped to [min, max]."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else PAGINATION_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise AppError(
            ERR_VALIDATION, "limit must be an integer.", ERROR_STATUS[ERR_VALIDATION]
        )
    try:
        offset = int(offset_raw) if offset_raw is not None else PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise AppError(
            ERR_VALIDATION, "offset must be an integer.", ERROR_STATUS[ERR_VALIDATION]
        )

    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise AppError(
            ERR_VALIDATION,
            f"limit must be between {PAGINATION_MIN_LIMIT} and {PAGINATION_MAX_LIMIT}.",
            ERROR_STATUS[ERR_VALIDATION],
        )
    if offset < 0:
        raise AppError(
            ERR_VALIDATION, "offset must be non-negative.", ERROR_STATUS[ERR_VALIDATION]
        )
    return limit, offset


def get_json_body() -> dict:
    """Return the request JSON body as a dict; empty dict if no body / no content."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=False)
    except Exception:
        raise AppError(
            ERR_VALIDATION, "Request body is not valid JSON.", ERROR_STATUS[ERR_VALIDATION]
        )
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AppError(
            ERR_VALIDATION, "Request body must be a JSON object.", ERROR_STATUS[ERR_VALIDATION]
        )
    return body
