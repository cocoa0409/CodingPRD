"""Shared helpers: record skeletons, mutation bookkeeping, body parsing,
pagination, filtered listing."""
from flask import request

import db
from errors import ApiError


# ---- record lifecycle ------------------------------------------------------
def base_record(common_fields=True):
    """Create a record skeleton with id/created_at (+ updated_at/version)."""
    rec = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at, bump version. No-op for Bid
    (records without a version field)."""
    if "version" in rec:
        rec["updated_at"] = db.now_iso()
        rec["version"] = rec["version"] + 1


# ---- request body ----------------------------------------------------------
def get_body():
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body.")
        if data is None:
            raise ApiError("ERR_VALIDATION", "Malformed JSON body.")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", "Request body must be an object.")
        return data
    return {}


def require_str(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    val = body[field]
    if not isinstance(val, str) or val.strip() == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None, positive=False):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % field)
    if positive and val <= 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be positive." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s." % (field, minimum))
    return val


def optional_int(body, field, default=None, minimum=None, positive=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer." % field)
    if positive and val <= 0:
        raise ApiError("ERR_VALIDATION", "Field %s must be positive." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s." % (field, minimum))
    return val


def require_number(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_VALIDATION", "Field %s must be <= %s." % (field, maximum))
    return val


def optional_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number." % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_VALIDATION", "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise ApiError("ERR_VALIDATION", "Field %s must be <= %s." % (field, maximum))
    return val


def require_enum(body, field, choices, default=None, required=True):
    if field not in body or body[field] is None:
        if required and default is None:
            raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in choices:
        raise ApiError("ERR_VALIDATION", "Field %s has an invalid value." % field)
    return val


# ---- pagination & listing --------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit_v < 1 or limit_v > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset_v < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0.")
    return limit_v, offset_v


def list_collection(collection, filters=None):
    """Return (page_items, limit, offset, total_count).

    filters: dict of field -> value; only records matching all are kept.
    Sorted by created_at ascending (using monotonic _seq for stable order).
    """
    limit, offset = parse_pagination()
    items = list(collection.values())
    if filters:
        for fld, val in filters.items():
            if val is not None:
                items = [r for r in items if r.get(fld) == val]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return [public(r) for r in page], limit, offset, total


# ---- serialization ---------------------------------------------------------
def public(rec):
    """Strip internal-only keys (those prefixed with _) before returning."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
