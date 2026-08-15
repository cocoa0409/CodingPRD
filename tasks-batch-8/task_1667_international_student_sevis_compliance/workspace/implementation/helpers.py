"""Shared request-validation and listing helpers for route handlers.

Field-shape failures raise ERR_INVALID_REQUEST (400); missing path resources
raise ERR_STUDENT_NOT_FOUND / ERR_NOT_FOUND (404) per PRD §2.6.
"""

from flask import request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_STUDENT_NOT_FOUND,
    raise_error,
)
from response import success_list


# ---------------------------------------------------------------------------
# Body parsing and field validators
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def req_field(data, field):
    if field not in data or data[field] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return data[field]


def req_str(data, field):
    value = req_field(data, field)
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return value


def opt_str(data, field):
    if field not in data or data[field] is None:
        return None
    value = data[field]
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return value


def req_int(data, field, min_value=None):
    value = req_field(data, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if min_value is not None and value < min_value:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {min_value}")
    return value


def opt_int(data, field, min_value=None):
    if field not in data or data[field] is None:
        return None
    if isinstance(data[field], bool) or not isinstance(data[field], int):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if min_value is not None and data[field] < min_value:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be >= {min_value}")
    return data[field]


def req_date(data, field):
    """Required ISO calendar date; returns the canonical YYYY-MM-DD string."""
    value = req_field(data, field)
    try:
        return db.parse_date(value).isoformat()
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 date (YYYY-MM-DD)")


def opt_date(data, field):
    if field not in data or data[field] is None:
        return None
    try:
        return db.parse_date(data[field]).isoformat()
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 date (YYYY-MM-DD)")


def req_enum(data, field, allowed):
    value = req_field(data, field)
    if not isinstance(value, str) or value not in allowed:
        raise_error(
            ERR_INVALID_REQUEST,
            f"Field '{field}' must be one of: {', '.join(allowed)}",
        )
    return value


def occ_token(data, field):
    """Required optimistic-concurrency token. Accepts an integer or a decimal
    string; anything else is a malformed request."""
    value = req_field(data, field)
    if isinstance(value, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise_error(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")


# ---------------------------------------------------------------------------
# Existence helpers (left-to-right path validation; PRD §2.6)
# ---------------------------------------------------------------------------

def get_student_or_404(student_id):
    student = db.students.get(student_id)
    if student is None:
        raise_error(ERR_STUDENT_NOT_FOUND, "Student not found")
    return student


def get_or_404(store, entity_id, what):
    entity = store.get(entity_id)
    if entity is None:
        raise_error(ERR_NOT_FOUND, f"{what} not found")
    return entity


# ---------------------------------------------------------------------------
# Pagination & listing (PRD §2.3: limit/offset, default 10/0, min 1 max 100;
# default sort created_at ascending)
# ---------------------------------------------------------------------------

def parse_pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "limit and offset must be integers")
    if isinstance(raw_limit, str) and raw_limit.strip() and not raw_limit.lstrip("+-").isdigit():
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    if isinstance(raw_offset, str) and raw_offset.strip() and not raw_offset.lstrip("+-").isdigit():
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(items, serializer, filters=None):
    """Sort by created_at ascending (insertion order on ties), apply equality
    filters, paginate, and render the array envelope."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    if filters:
        for field, value in filters.items():
            if value is not None:
                ordered = [e for e in ordered if e.get(field) == value]
    limit, offset = parse_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(e) for e in page], limit, offset, total)
