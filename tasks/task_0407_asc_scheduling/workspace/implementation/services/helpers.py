"""Shared lookup / validation / serialization helpers."""
from flask import request

from db import db
from errors import err

# Entity collection -> not-found error id.
NOT_FOUND = {
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "operating_rooms": "ERR_OPERATING_ROOM_NOT_FOUND",
    "recovery_bays": "ERR_RECOVERY_BAY_NOT_FOUND",
    "anesthesiologists": "ERR_ANESTHESIOLOGIST_NOT_FOUND",
    "surgeons": "ERR_SURGEON_NOT_FOUND",
    "procedures": "ERR_PROCEDURE_NOT_FOUND",
    "supply_items": "ERR_SUPPLY_ITEM_NOT_FOUND",
    "patients": "ERR_PATIENT_NOT_FOUND",
    "surgical_days": "ERR_SURGICAL_DAY_NOT_FOUND",
    "surgeon_blocks": "ERR_SURGEON_BLOCK_NOT_FOUND",
    "surgical_cases": "ERR_SURGICAL_CASE_NOT_FOUND",
    "case_implants": "ERR_CASE_IMPLANT_NOT_FOUND",
    "clearance_checks": "ERR_CLEARANCE_CHECK_NOT_FOUND",
}


def lookup(collection_name, entity_id):
    """Fetch a record by id from a named collection, or raise the not-found error."""
    coll = getattr(db, collection_name)
    rec = coll.get(entity_id)
    if rec is None:
        raise err(NOT_FOUND[collection_name],
                  "%s not found." % collection_name)
    return rec


def get_body():
    """Parse the JSON body; a missing/invalid body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be positive." % field)
    return v


def require_nonneg_int(body, field):
    v = require_int(body, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "Field %s must be non-negative." % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (field, sorted(allowed)))
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return v


def optional_bool(body, field, default):
    if body.get(field) is None:
        return default
    return require_bool(body, field)


def optional_int(body, field, default):
    if body.get(field) is None:
        return default
    return require_int(body, field)


def optional_number(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % field)
    return v


def paginate(items):
    """Apply limit/offset query params (PRD §2.3) to a pre-sorted list.

    Returns (page_items, limit, offset, total_count).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative.")

    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sorted_by_created(records):
    """PRD §2.3 — sort list results by created_at ascending (seq breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# --- Serializers: strip internal fields (_seq) from the public payload. ---

def _public(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ser_facility(f):
    return _public(f)


def ser_default(r):
    return _public(r)


def ser_supply_item(s):
    """SupplyItem exposes computed reserved_qty (already maintained on the record)."""
    return _public(s)


def ser_clearance_check(c):
    """ClearanceCheck is append-only: only id + created_at + content fields, no
    updated_at / version (PRD §2.4)."""
    return _public(c)
