"""Shared request-validation, pagination, and lookup helpers."""

from __future__ import annotations

from flask import request

import db
from errors import raise_err, ERR_INVALID_REQUEST

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
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_err(
                ERR_INVALID_REQUEST,
                "limit must be between {} and {}".format(MIN_LIMIT, MAX_LIMIT),
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    """Return (page_items, total_count). Items must already be sorted."""
    total = len(items)
    return items[offset : offset + limit], total


def sort_by_created_at(items: list) -> list:
    """Ascending creation order; insertion sequence breaks wall-clock ties."""
    return sorted(items, key=lambda it: (it.get("created_at", ""), it.get("_seq", 0)))


def apply_filters(items: list, filter_names) -> list:
    out = list(items)
    for name in filter_names:
        value = request.args.get(name)
        if value is not None and value != "":
            out = [it for it in out if it.get(name) is not None and str(it.get(name)) == value]
    return out


# ---------------------------------------------------------------------------
# Body field validation (priority-4 request shape)
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
        raise_err(ERR_INVALID_REQUEST, "Missing required field: {}".format(name))
    return body[name]


def require_string(body: dict, name: str) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, "Field {} must be a non-empty string".format(name))
    return value


def require_int(body: dict, name: str, minimum=None, maximum=None) -> int:
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, "Field {} must be an integer".format(name))
    if minimum is not None and value < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field {} must be >= {}".format(name, minimum))
    if maximum is not None and value > maximum:
        raise_err(ERR_INVALID_REQUEST, "Field {} must be <= {}".format(name, maximum))
    return value


def require_enum(body: dict, name: str, allowed) -> str:
    value = require_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise_err(
            ERR_INVALID_REQUEST,
            "Field {} must be one of {}".format(name, sorted(allowed)),
        )
    return value


def require_datetime(body: dict, name: str):
    """Require a valid ISO 8601 datetime; returns (raw_string, utc_datetime)."""
    value = require_field(body, name)
    dt = db.parse_datetime(value)
    if dt is None:
        raise_err(
            ERR_INVALID_REQUEST,
            "Field {} must be a valid ISO 8601 datetime".format(name),
        )
    return value, dt


def require_date_field(body: dict, name: str) -> str:
    value = require_field(body, name)
    if db.parse_date(value) is None:
        raise_err(
            ERR_INVALID_REQUEST,
            "Field {} must be an ISO 8601 date (YYYY-MM-DD)".format(name),
        )
    return value


# ---------------------------------------------------------------------------
# Entity lookup
# ---------------------------------------------------------------------------

def fetch_or_404(store_name: str, rec_id, error_id: str, label: str) -> dict:
    rec = db.STORES[store_name].get(rec_id) if isinstance(rec_id, str) else None
    if rec is None:
        raise_err(error_id, "No {} with the given id".format(label))
    return rec
