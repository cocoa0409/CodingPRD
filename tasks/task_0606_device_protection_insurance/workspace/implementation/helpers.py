"""Serialization, mutation, pagination, and lookup helpers."""
from flask import request

import errors
from clock import clock, to_iso
from db import db

# Fields that are datetimes and must be serialized via to_iso
DATETIME_FIELDS = {
    "created_at", "updated_at", "enrolled_at", "incident_at",
    "device_purchase_date", "return_due_at",
}


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in DATETIME_FIELDS and v is not None and not isinstance(v, str):
            out[k] = to_iso(v)
        else:
            out[k] = v
    return out


def touch(entity):
    """Bump version + updated_at for a versioned entity (logical clock for updated_at)."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = clock.now()


def base_system_fields(versioned=True):
    now = clock.now()
    fields = {"created_at": now}
    if versioned:
        fields["updated_at"] = now
        fields["version"] = 1
    return fields


def get_or_404(store, _id):
    if _id is None or _id not in store:
        errors.fail(errors.ERR_NOT_FOUND, "Resource not found")
    return store[_id]


def parse_pagination():
    """Return (limit, offset). Raise ERR_PAGINATION_INVALID on out-of-range."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_PAGINATION_INVALID, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            errors.fail(errors.ERR_PAGINATION_INVALID, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return slice."""
    return items[offset:offset + limit]


def sorted_by_created(values):
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))


def body():
    return request.get_json(silent=True) or {}


def require_str(b, field):
    v = b.get(field)
    if v is None or not isinstance(v, str) or v == "":
        errors.fail(errors.ERR_VALIDATION, f"{field} is required")
    return v


def require_int(b, field):
    v = b.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        errors.fail(errors.ERR_VALIDATION, f"{field} must be an integer")
    return v
