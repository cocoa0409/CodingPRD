"""Shared request-validation, pagination, and listing helpers."""

from __future__ import annotations

import re

from flask import request

from db import parse_instant
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FK_NOT_FOUND

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(ERR_INVALID_REQUEST, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def page_of(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


# ---------------------------------------------------------------------------
# Body field validation (ERR_INVALID_REQUEST, 400)
# ---------------------------------------------------------------------------


def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    return body[name]


def optional_field(body: dict, name: str, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return value


def optional_bool(body: dict, name: str, default: bool = False) -> bool:
    value = optional_field(body, name, default)
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return value


def require_int(body: dict, name: str, minimum=None, maximum=None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}")
    return value


def require_enum(body: dict, name: str, allowed) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return value


_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def require_state_code(body: dict, name: str) -> str:
    value = require_string(body, name)
    if not _STATE_CODE_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a two-letter state code")
    return value


def require_state_codes(body: dict, name: str) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    for item in value:
        if not isinstance(item, str) or not _STATE_CODE_RE.match(item):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must contain two-letter state codes")
    return list(value)


def require_string_list(body: dict, name: str, allowed=None) -> list:
    value = require_field(body, name)
    if not isinstance(value, list):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    for item in value:
        if not isinstance(item, str):
            raise_err(ERR_INVALID_REQUEST, f"Field {name} must contain strings")
        if allowed is not None and item not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"Field {name} contains an invalid value: {item}")
    return list(value)


def require_ts(body: dict, name: str) -> str:
    """Validate and return the caller-supplied ISO 8601 string verbatim."""
    value = require_field(body, name)
    if parse_instant(value) is None:
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a valid ISO 8601 timestamp")
    return value


def require_version(body: dict, name: str) -> int:
    """OCC expected_*_version fields are non-optional integers (PRD §2.8)."""
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return value


# ---------------------------------------------------------------------------
# Resource resolution
# ---------------------------------------------------------------------------


def path_or_404(store: dict, resource_id, label: str) -> dict:
    row = store.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {resource_id}")
    return row


def fk_or_404(store: dict, resource_id, label: str) -> dict:
    row = store.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise_err(ERR_FK_NOT_FOUND, f"Referenced {label} not found: {resource_id}")
    return row


def child_or_404(store: dict, child_id, parent_field: str, parent_id: str, label: str) -> dict:
    """Resolve a nested path identifier; the child must belong to the parent."""
    row = store.get(child_id) if isinstance(child_id, str) else None
    if row is None or row.get(parent_field) != parent_id:
        raise_err(ERR_NOT_FOUND, f"{label} not found: {child_id}")
    return row


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------


def apply_filters(items: list, filter_names) -> list:
    out = items
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if str(it.get(name)) == value]
    return out


def sort_created(items: list) -> list:
    """PRD §2.3: created_at ascending, oldest first; insertion order breaks ties."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))
