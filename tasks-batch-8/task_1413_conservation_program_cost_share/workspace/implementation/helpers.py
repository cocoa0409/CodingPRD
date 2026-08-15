"""Shared request/entity helpers: body parsing, field validation, existence,
pagination, mutation stamping."""
from flask import request

from db import STORE
from errors import ApiError
from util import is_int, is_num, parse_dt


# ---------- request body / fields ----------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")
    return data[name]


def as_str(v, name):
    if not isinstance(v, str) or not v:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a non-empty string")
    return v


def as_int(v, name):
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer")
    return v


def as_num(v, name):
    if not is_num(v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a number")
    return v


def as_list(v, name):
    if not isinstance(v, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an array")
    return v


def as_dt(v, name):
    dt = parse_dt(v)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an ISO-8601 datetime")
    return dt


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            f"Field {name} must be one of {sorted(allowed)}",
        )
    return v


# ---------- existence (404 family, validated left-to-right) ----------

def _get(table, rid, error_id):
    ent = table.get(rid) if isinstance(rid, str) else None
    if ent is None:
        raise ApiError(error_id, 404, f"Resource not found: {rid}")
    return ent


def get_program(rid):
    return _get(STORE.programs, rid, "ERR_PROGRAM_NOT_FOUND")


def get_pool(rid):
    return _get(STORE.pools, rid, "ERR_POOL_NOT_FOUND")


def get_applicant(rid):
    return _get(STORE.applicants, rid, "ERR_APPLICANT_NOT_FOUND")


def get_application(rid):
    return _get(STORE.applications, rid, "ERR_APPLICATION_NOT_FOUND")


def get_contract(rid):
    return _get(STORE.contracts, rid, "ERR_CONTRACT_NOT_FOUND")


def get_item(rid):
    return _get(STORE.items, rid, "ERR_PRACTICE_ITEM_NOT_FOUND")


def get_request(rid):
    return _get(STORE.payment_requests, rid, "ERR_PAYMENT_REQUEST_NOT_FOUND")


def get_advance(rid):
    return _get(STORE.advances, rid, "ERR_ADVANCE_PAYMENT_NOT_FOUND")


def get_modification(rid):
    return _get(STORE.modifications, rid, "ERR_MODIFICATION_NOT_FOUND")


def get_spot_check(rid):
    return _get(STORE.spot_checks, rid, "ERR_SPOT_CHECK_NOT_FOUND")


def get_obligation(rid):
    return _get(STORE.obligations, rid, "ERR_MAINTENANCE_OBLIGATION_NOT_FOUND")


def get_demand(rid):
    return _get(STORE.demands, rid, "ERR_RECOUPMENT_DEMAND_NOT_FOUND")


# ---------- pagination / listing ----------

def pagination_args():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(str(raw_limit), 10)
        offset = int(str(raw_offset), 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def sorted_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paginate(items):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def apply_filters(items, filters):
    """filters: list of (query_param_name, entity_field)."""
    out = items
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            out = [e for e in out if str(e.get(field)) == val]
    return out


# ---------- mutation stamping (PRD 2.4) ----------

def touch(ent):
    """Every mutation refreshes updated_at and increments version."""
    ent["version"] = ent.get("version", 1) + 1
    ent["updated_at"] = STORE.clock


def stamp_new(ent):
    """Initialize common system fields on a freshly built entity dict."""
    ent["created_at"] = STORE.clock
    if ent.get("_common_fields", True):
        ent["updated_at"] = STORE.clock
        ent["version"] = 1
    ent["_seq"] = STORE.next_seq()
    return ent
