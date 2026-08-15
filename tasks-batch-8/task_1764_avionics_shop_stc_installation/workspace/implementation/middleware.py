"""Auth extraction, role checks, body parsing, and field validators.

Validation order follows PRD section 2.11: authenticate -> authorize role ->
(customer ownership where the resource can be loaded) -> body schema ->
existence -> state -> safety -> temporal -> lineage -> uniqueness -> budget.
"""
import json

from flask import request

import errors
from errors import ApiError
from util import parse_dt

ROLES = {"ShopManager", "Technician", "Inspector", "Customer"}
ALL_ROLES = frozenset(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        errors.raise_err(
            errors.ERR_UNAUTHENTICATED,
            "Missing or unknown X-User-Role / X-User-ID headers",
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        errors.raise_err(errors.ERR_FORBIDDEN, "Role not permitted for this endpoint")


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        errors.raise_err(errors.ERR_VALIDATION, "Request body must be valid JSON")
    if not isinstance(data, dict):
        errors.raise_err(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def _missing(field):
    errors.raise_err(errors.ERR_VALIDATION, f"Missing required field: {field}")


def _bad(field, detail):
    errors.raise_err(errors.ERR_VALIDATION, f"Invalid value for field {field}: {detail}")


def req_str(b, field):
    v = b.get(field)
    if v is None:
        _missing(field)
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def opt_str(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_num(b, field):
    v = b.get(field)
    if v is None:
        _missing(field)
    if not _is_num(v):
        _bad(field, "must be a number")
    return v


def opt_num(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not _is_num(v):
        _bad(field, "must be a number")
    return v


def req_int(b, field):
    v = b.get(field)
    if v is None:
        _missing(field)
    if not _is_int(v):
        _bad(field, "must be an integer")
    return int(v)


def opt_int(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not _is_int(v):
        _bad(field, "must be an integer")
    return int(v)


def req_enum(b, field, allowed):
    v = b.get(field)
    if v is None:
        _missing(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, f"must be one of {sorted(allowed)}")
    return v


def req_dt(b, field):
    v = b.get(field)
    if v is None:
        _missing(field)
    try:
        return parse_dt(v)
    except Exception:
        _bad(field, "must be an ISO 8601 datetime")


def req_equipment_list(b, field="equipment_list"):
    v = b.get(field)
    if v is None:
        _missing(field)
    if not isinstance(v, list):
        _bad(field, "must be an array")
    lines = []
    for i, ln in enumerate(v):
        if not isinstance(ln, dict):
            _bad(field, f"line {i} must be an object")
        part_number = req_str(ln, "part_number")
        description = req_str(ln, "description")
        quantity = req_int(ln, "quantity")
        if quantity < 1:
            _bad("quantity", "must be at least 1")
        unit_price_cents = req_int(ln, "unit_price_cents")
        if unit_price_cents <= 0:
            _bad("unit_price_cents", "must be greater than 0")
        weight_lb = req_num(ln, "weight_lb")
        arm_in = req_num(ln, "arm_in")
        lead_time_days = req_int(ln, "lead_time_days")
        if lead_time_days < 0:
            _bad("lead_time_days", "must be zero or more")
        lines.append(
            {
                "part_number": part_number,
                "description": description,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "weight_lb": weight_lb,
                "arm_in": arm_in,
                "lead_time_days": lead_time_days,
            }
        )
    return lines


def opt_added_items(b, field="added_items"):
    v = b.get(field)
    if v is None:
        return []
    if not isinstance(v, list):
        _bad(field, "must be an array")
    items = []
    for i, ln in enumerate(v):
        if not isinstance(ln, dict):
            _bad(field, f"line {i} must be an object")
        items.append(
            {
                "description": req_str(ln, "description"),
                "weight_lb": req_num(ln, "weight_lb"),
                "arm_in": req_num(ln, "arm_in"),
            }
        )
    return items


def pagination_args():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit, offset = 10, 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            errors.raise_err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.raise_err(errors.ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            errors.raise_err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            errors.raise_err(errors.ERR_VALIDATION, "offset must be zero or more")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted; returns (page, pagination-meta-dict)."""
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
