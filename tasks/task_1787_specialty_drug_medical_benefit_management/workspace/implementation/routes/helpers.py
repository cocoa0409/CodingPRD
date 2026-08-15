"""Shared route helpers: body parsing, shape validators, pagination, lists,
record stamping, and ProviderRep scoping (PRD 2.1/2.2/2.3/2.5)."""
from flask import request

from db import db, next_seq
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_PROVIDER_SCOPE_VIOLATION
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from util import CLOCK, new_id, parse_date_strict


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def stamp_new(rec: dict, common: bool = True):
    rec["_seq"] = next_seq()
    rec["created_at"] = CLOCK.ts()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1


def get_or_404(collection: str, rid: str):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{collection[:-1]} {rid} does not exist")
    return rec


# ---------------------------------------------------------------------------
# Request body + shape validators (pipeline stage 4: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def get_body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body: dict, field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return v


def opt_str(body: dict, field: str, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def req_bool(body: dict, field: str) -> bool:
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be a boolean")
    return v


def opt_bool(body: dict, field: str, default=False) -> bool:
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def req_int(body: dict, field: str, min_v=None, max_v=None) -> int:
    v = body.get(field)
    if not is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    if min_v is not None and v < min_v:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be <= {max_v}")
    return v


def opt_int(body: dict, field: str, default=None, min_v=None):
    v = body.get(field)
    if v is None:
        return default
    if not is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {min_v}")
    return v


def req_num(body: dict, field: str, gt=None, ge=None, le=None, lt=None):
    v = body.get(field)
    if not is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be a number")
    _range_check(v, field, gt, ge, le, lt)
    return v


def opt_num(body: dict, field: str, default=None, gt=None, ge=None, le=None, lt=None):
    v = body.get(field)
    if v is None:
        return default
    if not is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a number")
    _range_check(v, field, gt, ge, le, lt)
    return v


def _range_check(v, field, gt, ge, le, lt):
    if gt is not None and not v > gt:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be > {gt}")
    if ge is not None and not v >= ge:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {ge}")
    if le is not None and not v <= le:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be <= {le}")
    if lt is not None and not v < lt:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be < {lt}")


def req_enum(body: dict, field: str, allowed) -> str:
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be one of {list(allowed)}")
    return v


def req_date(body: dict, field: str):
    v = body.get(field)
    try:
        return parse_date_strict(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be an ISO date (YYYY-MM-DD)")


def req_list_str(body: dict, field: str, non_empty=False):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be a list of strings")
    if non_empty and len(v) == 0:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a non-empty list")
    return v


# ---------------------------------------------------------------------------
# Pagination + list responses (PRD 2.3)
# ---------------------------------------------------------------------------

def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def list_response(items):
    """Sort by creation order, paginate, and wrap in the array envelope."""
    items = sorted(items, key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def apply_filters(items, fields):
    for field in fields:
        v = request.args.get(field)
        if v is not None:
            items = [r for r in items if str(r.get(field)) == v]
    return items


# ---------------------------------------------------------------------------
# ProviderRep scope guard (PRD 2.1; pipeline stage 3)
# ---------------------------------------------------------------------------

def scope_list_for_provider(caller, items, provider_of, foreign_filter_checks):
    """ProviderRep list scoping: explicit foreign filters are rejected, otherwise
    the list is silently scoped to the caller's own account.

    foreign_filter_checks: list of (query_param, owner_lookup) where owner_lookup
    maps the filter value to the owning provider_account_id (or None if the
    named resource does not exist -> no rejection, just filtering).
    """
    if caller.role != "ProviderRep":
        return items
    for param, owner_lookup in foreign_filter_checks:
        v = request.args.get(param)
        if v is None:
            continue
        owner = owner_lookup(v)
        if owner is not None and owner != caller.user_id:
            raise_error(
                ERR_PROVIDER_SCOPE_VIOLATION,
                f"{param} filter addresses a resource of another provider account",
            )
    return [r for r in items if provider_of(r) == caller.user_id]


def check_single_scope(caller, owner_provider_id):
    if caller.role == "ProviderRep" and owner_provider_id != caller.user_id:
        raise_error(
            ERR_PROVIDER_SCOPE_VIOLATION,
            "resource belongs to a different provider account",
        )


def read_all():
    """Auth for the shared all-roles GET endpoints."""
    return authorized(ALL_ROLES)


def one(collection, rid):
    return success_object(public(get_or_404(collection, rid)))
