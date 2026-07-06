from flask import request

from db import db, new_id, fmt_dt
from errors import err

# Fields on each entity dict that are datetime objects and must be formatted.
DT_FIELDS = {"created_at", "updated_at", "surgery_completed_at", "signed_at", "slot_start", "slot_end"}


def stamp_create(record, tracked=True):
    """Attach system common fields on create. tracked=False for TreatmentPackage."""
    record["id"] = new_id()
    record["created_at"] = db.now()
    if tracked:
        record["updated_at"] = db.now()
        record["version"] = 1
    return record


def touch(record):
    """Register a mutation: bump updated_at + version (if tracked)."""
    if "version" in record:
        record["version"] += 1
        record["updated_at"] = db.now()


def serialize(record):
    out = {}
    for k, v in record.items():
        if k in DT_FIELDS and v is not None:
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------- Request body / validation helpers ----------------

def get_json_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if body is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return body
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def as_int(body, field, allow_missing=False):
    if field not in body or body[field] is None:
        if allow_missing:
            return None
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return v


def as_number(body, field, allow_missing=False):
    if field not in body or body[field] is None:
        if allow_missing:
            return None
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return v


def as_str(body, field, allow_missing=False):
    if field not in body or body[field] is None:
        if allow_missing:
            return None
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % field)
    return v


def as_bool(body, field, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def as_enum(body, field, choices, allow_missing=False, default=None):
    if field not in body or body[field] is None:
        if allow_missing:
            return default
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    v = body[field]
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, choices))
    return v


# ---------------- Existence helpers ----------------

def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found: %s" % rid)
    return rec


# ---------------- Pagination ----------------

def paginate(items):
    """Apply limit/offset from query string. Returns (page, meta_dict)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0

    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))
