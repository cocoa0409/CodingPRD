"""Shared route helpers: pagination, list responses, case serialization."""
from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import ALL_READ_ROLES, authorized
from response import success_list, success_object
from services.calculations import revenue_requirement
from services.core import public, sort_rows
from validate import require_path_resource


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


def list_response(collection, filters=None, sort_key=None):
    authorized(ALL_READ_ROLES)
    items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    if sort_key is not None:
        items.sort(key=sort_key)
    else:
        items = sort_rows(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_record(collection, r) for r in page], total, limit, offset)


def get_one(collection, rid):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource(collection, rid)
    return success_object(serialize_record(collection, rec))


def serialize_record(collection, rec):
    if collection == "rate_cases":
        return serialize_case(rec)
    return public(rec)


def serialize_case(case):
    """Computed fields are mirrored on read (PRD 3.8); counters are stored."""
    out = public(case)
    out["present_revenue_total_cents"] = sum(
        c["present_revenue_cents"]
        for c in db["customer_classes"].values()
        if c["rate_case_id"] == case["id"]
    )
    out["revenue_requirement_as_filed_cents"] = revenue_requirement(case, "as_filed")["revenue_requirement_cents"]
    out["revenue_requirement_as_audited_cents"] = revenue_requirement(case, "as_audited")["revenue_requirement_cents"]
    out["revenue_at_approved_rates_cents"] = sum(
        c["approved_revenue_cents"]
        for c in db["customer_classes"].values()
        if c["rate_case_id"] == case["id"] and c["approved_revenue_cents"] is not None
    )
    return out


def query_arg(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
