"""Request helpers: auth context, body parsing, field validation, pagination.

Validation families run in the PRD §2.10 order inside every handler:
auth(1) -> role(2) -> existence(3) -> state(4) -> parent-active(5) ->
cross-reference(6) -> governance(7) -> completeness(8) -> temporal(9) ->
numeric/enum/unknown-field sanity(10).
"""

import math
import re
from decimal import Decimal

from flask import request

import errors

ALL_ROLES = ("CostAnalyst", "FinanceController", "ServiceLineManager")

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Auth (families 1-2)
# ---------------------------------------------------------------------------

def auth(*allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        errors.missing_user_context()
    if role not in allowed_roles:
        errors.insufficient_permissions(role)
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing + field validators (family 10 unless noted)
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.invalid_request("Request body must be a JSON object")
    return data


def check_unknown_fields(body, allowed):
    extra = sorted(set(body.keys()) - set(allowed))
    if extra:
        errors.invalid_request("Unknown field(s): %s" % ", ".join(extra))


def _missing(name):
    errors.invalid_request("Missing required field: %s" % name)


def get_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, str):
        errors.invalid_request("Field %s must be a string" % name)
    return v


def get_number(body, name, required=True, gt=None, ge=None, le=None):
    """Return a Decimal for a JSON number field."""
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.invalid_request("Field %s must be a number" % name)
    if isinstance(v, float) and not math.isfinite(v):
        errors.invalid_request("Field %s must be finite" % name)
    d = Decimal(str(v))
    if gt is not None and not d > Decimal(str(gt)):
        errors.invalid_request("Field %s must be > %s" % (name, gt))
    if ge is not None and not d >= Decimal(str(ge)):
        errors.invalid_request("Field %s must be >= %s" % (name, ge))
    if le is not None and not d <= Decimal(str(le)):
        errors.invalid_request("Field %s must be <= %s" % (name, le))
    return d


def get_int(body, name, required=True, gt=None, ge=None):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if isinstance(v, bool):
        errors.invalid_request("Field %s must be an integer" % name)
    if isinstance(v, float):
        if not math.isfinite(v) or not v.is_integer():
            errors.invalid_request("Field %s must be an integer" % name)
        v = int(v)
    if not isinstance(v, int):
        errors.invalid_request("Field %s must be an integer" % name)
    if gt is not None and not v > gt:
        errors.invalid_request("Field %s must be > %s" % (name, gt))
    if ge is not None and not v >= ge:
        errors.invalid_request("Field %s must be >= %s" % (name, ge))
    return v


def get_bool(body, name, required=False):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, bool):
        errors.invalid_request("Field %s must be a boolean" % name)
    return v


def get_enum(body, name, values, required=True):
    v = get_str(body, name, required=required)
    if v is None:
        return None
    if v not in values:
        errors.invalid_request(
            "Field %s must be one of %s" % (name, ", ".join(values)))
    return v


def get_period(body, name, required=True):
    """Presence/type here; YYYY-MM shape is family 9 (checked separately)."""
    return get_str(body, name, required=required)


def check_period_format(value, field="period"):
    """Family 9: temporal windowing — period must match YYYY-MM."""
    if value is None:
        return
    if not isinstance(value, str) or not PERIOD_RE.match(value):
        errors.invalid_period_format(value)


def occ_matches(body, model):
    """Non-raising OCC probe used mid-validation-chain."""
    if "expected_model_version" not in body or body.get("expected_model_version") is None:
        return True
    v = body.get("expected_model_version")
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return v == model["version"]
    if isinstance(v, float) and math.isfinite(v) and v.is_integer():
        return int(v) == model["version"]
    return False


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.invalid_request("limit must be an integer")
        if limit < 1:
            errors.invalid_request("limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.invalid_request("offset must be an integer")
        if offset < 0:
            errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
