"""Shared helpers: common-field stamping, pagination, input parsing, money math."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import db, new_id, now_iso


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------
def stamp_new(record, common=True):
    """Attach id + system fields to a freshly created record.

    common=True records get created_at/updated_at/version.
    common=False (ledger lines) get only id + created_at.
    """
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version for any mutation (incl. cascades)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serialization — strip internal-only fields (those starting with '_')
# ---------------------------------------------------------------------------
def serialize(record):
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return data
    return {}


# ---------------------------------------------------------------------------
# Field validation primitives (ERR_INVALID_REQUEST / 422)
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {n}")


def as_int(body, name, required=True, default=None, minimum=None):
    if name not in body or body.get(name) is None:
        if required:
            errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return val


def as_number(body, name, required=True, default=None, gt=None):
    if name not in body or body.get(name) is None:
        if required:
            errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if gt is not None and not (val > gt):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be > {gt}")
    return val


def as_bool(body, name, default=False):
    if name not in body or body.get(name) is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return val


def as_str(body, name, required=True, default=None, non_empty=False):
    if name not in body or body.get(name) is None:
        if required:
            errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, str):
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a string")
    if non_empty and val.strip() == "":
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be non-empty")
    return val


def as_enum(body, name, choices, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    val = body[name]
    if val not in choices:
        errors.err(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(choices)}")
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records):
    """Sort by created_at asc (tie-break by creation sequence), then page."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
