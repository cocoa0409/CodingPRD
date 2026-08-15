"""Core services: serialisation, pagination, validation helpers, shared lookups."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_CLINIC_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_AUTHORIZATION_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_BACKORDER_LINE_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_CREDIT_NOT_FOUND,
    ERR_CLINIC_NOT_ACTIVE,
)
from util import parse_datetime, parse_date


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be <= {maximum}")
    return v


def optional_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return None
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST,
                    f"field {field} must be one of {sorted(allowed)}")
    return v


def require_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return v


def parse_dt_field(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 string")
    try:
        return parse_datetime(v)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, f"field {field} is not a valid ISO 8601 datetime")


def parse_date_field(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an ISO date string")
    try:
        return parse_date(v)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, f"field {field} is not a valid ISO date")


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0;
# every list sorted by created_at ascending)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ASC (ties by id for determinism) and slice."""
    limit, offset = pagination_params()
    items = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


# ---------------------------------------------------------------------------
# Existence lookups (pipeline step 4) — left-to-right resolution is handled by
# call order in the route handlers.
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "clinics": ERR_CLINIC_NOT_FOUND,
    "products": ERR_PRODUCT_NOT_FOUND,
    "manufacturer_authorizations": ERR_AUTHORIZATION_NOT_FOUND,
    "inventory_lots": ERR_LOT_NOT_FOUND,
    "orders": ERR_ORDER_NOT_FOUND,
    "order_lines": ERR_ORDER_LINE_NOT_FOUND,
    "backorder_lines": ERR_BACKORDER_LINE_NOT_FOUND,
    "shipments": ERR_SHIPMENT_NOT_FOUND,
    "bundle_programs": ERR_PROGRAM_NOT_FOUND,
    "bundle_enrollments": ERR_ENROLLMENT_NOT_FOUND,
    "short_date_credits": ERR_CREDIT_NOT_FOUND,
}


def get_or_404(collection, record_id):
    rec = db[collection].get(record_id)
    if rec is None:
        raise_error(_NOT_FOUND[collection], f"{collection[:-1]} not found: {record_id}")
    return rec


def get_clinic_or_404(clinic_id):
    return get_or_404("clinics", clinic_id)


def require_clinic_active(clinic):
    if clinic["status"] != "ACTIVE":
        raise_error(ERR_CLINIC_NOT_ACTIVE, "clinic must be ACTIVE for this operation")


# ---------------------------------------------------------------------------
# Serialisation — every resource carries id/created_at/updated_at/version.
# ---------------------------------------------------------------------------

def public(record):
    """Serialise a record, hiding internal bookkeeping fields (prefixed '_')."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
