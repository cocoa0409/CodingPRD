"""Shared route helpers."""

from flask import request
import errors
import db


def get_json_body():
    """Parse JSON body, raise ERR_VALIDATION on failure."""
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        raise errors.make_error(errors.ERR_VALIDATION, "Invalid JSON body")
    if not isinstance(body, dict):
        raise errors.make_error(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Check required fields present."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.make_error(errors.ERR_VALIDATION, f"Missing required field: {f}")


def validate_enum(value, allowed, field_name):
    if value not in allowed:
        raise errors.make_error(errors.ERR_VALIDATION, f"Invalid {field_name}: {value}")


def validate_positive_int(value, field_name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise errors.make_error(errors.ERR_VALIDATION, f"{field_name} must be a positive integer")


def validate_date_string(value, field_name):
    if not isinstance(value, str):
        raise errors.make_error(errors.ERR_VALIDATION, f"{field_name} must be a date string")
    try:
        from datetime import datetime
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise errors.make_error(errors.ERR_VALIDATION, f"{field_name} must be a valid ISO date (YYYY-MM-DD)")


def get_or_404(store, entity_id, label="Resource"):
    entity = store.get(entity_id)
    if entity is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, f"{label} not found: {entity_id}")
    return entity


def paginate(items, args):
    """Apply limit/offset pagination. Returns (page_items, limit, offset, total_count)."""
    try:
        limit = int(args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)

    # Sort by created_at ascending
    items_sorted = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, limit, offset, total


def serialize_common(entity, exclude_internal=True):
    """Return a copy of the entity dict with internal keys removed."""
    result = {k: v for k, v in entity.items() if not k.startswith("_")}
    return result
