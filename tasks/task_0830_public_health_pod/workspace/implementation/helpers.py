"""Shared request/response plumbing used by every route module."""
import uuid

from flask import request

from db import db
from errors import ApiError, NOT_FOUND_ERROR_FOR_ENTITY
from timeutil import new_timestamp_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def new_id() -> str:
    return str(uuid.uuid4())


def get_json_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.", 400)
    return body


def require_fields(body: dict, fields: list):
    for f in fields:
        if f not in body or body[f] is None or (isinstance(body[f], str) and body[f] == ""):
            raise ApiError("ERR_VALIDATION", f"Missing required field: {f}", 400)


def require_enum(value, allowed: set, field_name: str):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"Field {field_name} must be one of {sorted(allowed)}.", 400)


def require_type(value, expected_type, field_name: str):
    if expected_type is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_VALIDATION", f"Field {field_name} must be an integer.", 400)
    elif expected_type is str:
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", f"Field {field_name} must be a string.", 400)
    elif expected_type is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_VALIDATION", f"Field {field_name} must be a number.", 400)


def fetch_or_404(store: dict, entity_id, entity_name: str) -> dict:
    row = store.get(entity_id)
    if row is None:
        raise ApiError(NOT_FOUND_ERROR_FOR_ENTITY[entity_name], f"{entity_name} {entity_id} not found.", 404)
    return row


def new_common_fields() -> dict:
    ts = new_timestamp_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row: dict):
    """Mark a resource as mutated: advances updated_at, bumps version by 1."""
    row["updated_at"] = new_timestamp_iso()
    row["version"] = row.get("version", 1) + 1


def strip_internal(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def parse_pagination(args) -> tuple:
    limit_raw = args.get("limit", PAGINATION_DEFAULT_LIMIT)
    offset_raw = args.get("offset", PAGINATION_DEFAULT_OFFSET)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit must be an integer.", 400)
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "offset must be an integer.", 400)
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(rows, limit, offset):
    total_count = len(rows)
    page = rows[offset: offset + limit]
    return [strip_internal(r) for r in page], total_count
