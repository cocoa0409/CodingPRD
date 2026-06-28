"""Shared route helpers: body parsing, pagination, field validation, mutation."""
from datetime import datetime, timezone

from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from db import db
from util import iso_now

# Pagination defaults (PRD §2.3 / SCAFFOLD response_envelope.pagination_defaults).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def get_json_body():
    """Parse request JSON body. Missing/invalid JSON -> {} (treated as empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def parse_pagination():
    """Parse and clamp limit/offset query params (PRD §2.3)."""
    limit = _parse_int_param("limit", DEFAULT_LIMIT)
    offset = _parse_int_param("offset", DEFAULT_OFFSET)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items, limit, offset):
    """Return (page_items, total_count). items must already be sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_creation(items):
    """Sort a list of entity dicts by creation order ascending (PRD §2.3)."""
    return sorted(items, key=lambda x: x["_seq"])


def touch_and_bump(entity):
    """Refresh updated_at and increment version (PRD §2.4) for version-bearing rows."""
    entity["updated_at"] = iso_now(datetime.now(timezone.utc))
    entity["version"] += 1


# ---------------------------------------------------------------------------
# Field validation primitives (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, f"missing required field: {name}")
    return body[name]


def require_string(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, f"field {name} must be a non-empty string")
    return value


def require_int(body, name):
    value = require_field(body, name)
    # Reject bool (bool is a subclass of int) and non-int types.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    return value


def require_enum(body, name, allowed):
    value = require_string(body, name)
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"field {name} must be one of {sorted(allowed)}")
    return value


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, f"field {name} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND for path params)
# ---------------------------------------------------------------------------
def get_or_404(store, entity_id):
    entity = store.get(entity_id)
    if entity is None:
        raise err(ERR_NOT_FOUND, "resource not found")
    return entity
