"""Request parsing, pagination, lookups, and common validation helpers."""
from flask import request

import errors
from errors import err
from db import db


def get_json_body():
    """Return the parsed JSON body, or {} when absent. Raise ERR_VALIDATION (400)
    when the body is present but not parseable JSON (PRD §2.8)."""
    if request.content_length in (None, 0) and not (request.data or b""):
        return {}
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise err(errors.ERR_VALIDATION, "Request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise err(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return parsed


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Raise ERR_INVALID_REQUEST on bad values."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def lookup(collection, entity_id, name="resource"):
    ent = collection.get(entity_id)
    if ent is None:
        raise err(errors.ERR_NOT_FOUND, f"{name} {entity_id} not found")
    return ent


def require_tenant_owns_lease(user_id, role, lease):
    """When acting as a Tenant, the lease's tenant_id must equal the caller's id."""
    if role == "Tenant" and lease["tenant_id"] != user_id:
        raise err(errors.ERR_FORBIDDEN, "Tenant may only act on their own lease")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def as_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer")
    return val


def as_number(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be a number")
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be a string")
    return val


def as_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return val
