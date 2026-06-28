"""Shared helpers: body parsing, validation primitives, pagination, common fields."""

from flask import request

import errors
from clock import server_now_iso
import db


def get_json_body():
    """Parse the JSON body; return {} when absent. Malformed JSON -> 400."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def stamp_create(record):
    """Apply system common fields on create: id, created_at, updated_at, version."""
    now = server_now_iso()
    record["id"] = db.new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Bump version + updated_at on a mutation (incl. cascaded side effects)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = server_now_iso()


# ----- field validation primitives -----

def require_str(body, field, min_len=1, max_len=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be a string.")
    stripped_len = len(val)
    if stripped_len < min_len:
        raise errors.invalid_request(f"Field '{field}' is too short.")
    if max_len is not None and stripped_len > max_len:
        raise errors.invalid_request(f"Field '{field}' is too long.")
    return val


def require_enum(body, field, allowed):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if val not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}.")
    return val


def require_int(body, field, minimum=None, positive=False):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if positive and val <= 0:
        raise errors.invalid_request(f"Field '{field}' must be positive.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    return val


def optional_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{field}' must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{field}' must be >= {minimum}.")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{field}' must be a boolean.")
    return val


def require_datetime(body, field):
    from clock import parse_iso8601
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field '{field}'.")
    val = body[field]
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 string.")
    try:
        return parse_iso8601(val)
    except Exception:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 timestamp.")


# ----- pagination (PRD §2.3) -----

def parse_pagination():
    """Return (limit, offset). limit defaults 10, [1,100]; offset defaults 0, >=0.

    Out-of-bound limit/offset -> ERR_VALIDATION_LIMIT (422).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation_limit("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_limit("offset must be an integer.")
        if offset < 0:
            raise errors.validation_limit("offset must be >= 0.")

    return limit, offset


def paginate(records):
    """Sort by creation order (_seq ASC) then apply limit/offset.

    Returns (page_items, limit, offset, total_count).
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# ----- serialization (hide internal fields) -----

def public(record, fields):
    """Return a dict with only the named fields, in order."""
    return {f: record.get(f) for f in fields}
