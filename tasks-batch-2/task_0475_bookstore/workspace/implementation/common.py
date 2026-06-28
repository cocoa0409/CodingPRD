"""Record creation, mutation, and common-field stamping helpers."""
from flask import request

from db import db, new_id, now_iso
from errors import err, ERR_INVALID_REQUEST


def json_body(optional=True):
    """Parse the JSON request body. For transition endpoints that may carry no
    body, return {} when empty. Raise ERR_INVALID_REQUEST on malformed JSON.
    """
    if not request.data or request.data.strip() == b"":
        if optional:
            return {}
        raise err(ERR_INVALID_REQUEST, "Request body required")
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        if optional:
            return {}
        raise err(ERR_INVALID_REQUEST, "Request body required")
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def make_record(extra, with_common=True):
    """Create a base record dict with id and (optionally) common fields."""
    rec = {"id": new_id()}
    if with_common:
        ts = now_iso()
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = db.next_seq()  # internal ordering key, stripped on serialization
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a record as mutated: refresh updated_at and bump version.

    CreditLedgerEntry is immutable (no version/updated_at) and must never be touched.
    """
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()


def refresh_updated_at(rec):
    """Refresh updated_at WITHOUT bumping version. Used when a child mutation
    refreshes a parent's derived field but must not advance the parent's OCC
    token (e.g. adding an order line refreshes SalesOrder.subtotal_cents but
    leaves its version intact, so a reserve with the create-time version still
    succeeds)."""
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()


# ---- request body / query parsing -----------------------------------------

def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def get_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def get_int(body, field, required=True, default=None, minimum=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    # bool is a subclass of int — reject it
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def get_bool(body, field, required=False, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


def get_enum(body, field, choices, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in choices:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {choices}")
    return val


# ---- pagination -----------------------------------------------------------

def parse_pagination(args):
    """Parse limit/offset query params (PRD §2.3): limit default 10, min 1,
    max 100; offset default 0. Invalid values are clamped/defaulted (lenient).
    """
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation order then slice. Returns (page, total_count)."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
