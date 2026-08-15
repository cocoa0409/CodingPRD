"""Shared route helpers: serialization, pagination, list filtering, scoping."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_ROLES, authorized, check_grower_scope, grower_scope_id
from response import success_list, success_object


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


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
        if isinstance(limit, bool) or limit < 1 or limit > 100:
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


# Collections whose records carry a grower identity for GrowerRep scoping (PRD §2.1).
GROWER_SCOPE_FIELD = {
    "growers": "id",
    "contracts": "grower_id",
    "lots": "grower_id",
    "settlements": "grower_id",
}

NOT_FOUND = {
    "seasons": "ERR_SEASON_NOT_FOUND",
    "growers": "ERR_GROWER_NOT_FOUND",
    "contracts": "ERR_CONTRACT_NOT_FOUND",
    "bins": "ERR_BIN_NOT_FOUND",
    "lots": "ERR_LOT_NOT_FOUND",
    "drying_runs": "ERR_DRYING_RUN_NOT_FOUND",
    "mill_runs": "ERR_MILL_RUN_NOT_FOUND",
    "packaging_runs": "ERR_PACKAGING_RUN_NOT_FOUND",
    "byproduct_orders": "ERR_BYPRODUCT_ORDER_NOT_FOUND",
    "fumigation_events": "ERR_FUMIGATION_NOT_FOUND",
    "holds": "ERR_HOLD_NOT_FOUND",
    "settlements": "ERR_SETTLEMENT_NOT_FOUND",
}

ERROR_SPECS = {}  # populated lazily to avoid circular import


def _err_spec(collection):
    import errors as E
    name = NOT_FOUND[collection]
    return getattr(E, name)


def require_resource(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(_err_spec(collection), f"{collection} id not found: {rid}")
    return rec


def list_endpoint(collection, filter_fields):
    """GET collection: auth (any declared role), GrowerRep scoping, filters, pagination."""
    caller = authorized(ALL_ROLES)
    items = list(db[collection].values())
    scope_field = GROWER_SCOPE_FIELD.get(collection)
    scope = grower_scope_id(caller)
    if scope is not None and scope_field is not None:
        items = [r for r in items if r.get(scope_field) == scope]
    for field in filter_fields:
        value = request.args.get(field)
        if value is None:
            continue
        items = [r for r in items if r.get(field) is not None and str(r.get(field)) == value]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_endpoint(collection, rid):
    """GET one: auth, existence (404), GrowerRep scope (403)."""
    caller = authorized(ALL_ROLES)
    rec = require_resource(collection, rid)
    scope_field = GROWER_SCOPE_FIELD.get(collection)
    if scope_field is not None:
        check_grower_scope(caller, rec.get(scope_field))
    return success_object(public(rec))
