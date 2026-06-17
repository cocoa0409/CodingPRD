"""Shared helpers: common fields, pagination, request parsing, serialization."""
from flask import request

import errors
from errors import err
from db import db, new_id, now_iso


# --------------------------------------------------------------------------
# Common fields (PRD §2.4): id, created_at, updated_at, version on most
# entities; ConditionPhoto carries only id + created_at.
# --------------------------------------------------------------------------
def base_record(common=True):
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version (where carried)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] = rec["version"] + 1


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, 1..100; offset default 0, >= 0.
# --------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_PAGINATION, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_PAGINATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(errors.ERR_INVALID_PAGINATION, "limit out of bounds (1..100)")
    if offset < 0:
        raise err(errors.ERR_INVALID_PAGINATION, "offset may not be negative")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (tie-broken by mint sequence) then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# --------------------------------------------------------------------------
# Request body parsing.
# --------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            data = request.get_json(silent=True)
        except Exception:
            data = None
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return data
    return {}


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {n}")


def require_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def require_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def require_number(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def optional_number(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    return v


def optional_int(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def optional_string(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}")
    return v


# --------------------------------------------------------------------------
# Existence lookups.
# --------------------------------------------------------------------------
def get_work_order_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise err(errors.ERR_WORK_ORDER_NOT_FOUND, "Work order not found")
    return wo


def get_resource_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_RESOURCE_NOT_FOUND, "Resource not found")
    return rec


def get_fk_or_404(collection, fk_id):
    rec = collection.get(fk_id)
    if rec is None:
        raise err(errors.ERR_FK_NOT_FOUND, "Referenced resource not found")
    return rec


# --------------------------------------------------------------------------
# Serialization: strip internal fields (_seq, _reserved_yards bookkeeping).
# --------------------------------------------------------------------------
_INTERNAL_PREFIX = "_"


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith(_INTERNAL_PREFIX)}


def serialize_list(records):
    return [serialize(r) for r in records]
