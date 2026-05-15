"""Common request-parsing and validation helpers."""

from flask import request

from errors import (
    ERR_VALIDATION,
    ERR_INVALID_PAGINATION,
    ERR_VERSION_CONFLICT,
    raise_error,
)
from db import DB
from services.time_util import format_iso, now_iso


def get_json_body():
    """Return JSON body or {} for empty bodies; reject malformed JSON."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_error(ERR_VALIDATION, "Malformed JSON body")
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error(ERR_VALIDATION, f"Missing required field: {f}")


def parse_pagination():
    """Parse limit/offset query params per scaffold defaults."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_PAGINATION, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_PAGINATION, "limit out of bounds [1,100]")
    if offset < 0:
        raise_error(ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def check_version(body, current_row, field_name="version"):
    """OCC: PATCH endpoints require client-supplied version. Missing or
    mismatching version is rejected with ERR_VERSION_CONFLICT per PRD §2.4
    — except missing field is itself a malformed body (ERR_VALIDATION).
    """
    if field_name not in body or body[field_name] is None:
        raise_error(ERR_VALIDATION, f"Missing required field: {field_name}")
    supplied = body[field_name]
    if not isinstance(supplied, int) or supplied != current_row.get("version"):
        raise_error(ERR_VERSION_CONFLICT, "Stale version")


def bump_version(row):
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso()


def fmt_dt_field(row, field):
    """Return ISO string from a datetime-or-string field on a row."""
    v = row.get(field)
    return format_iso(v) if v is not None else None
