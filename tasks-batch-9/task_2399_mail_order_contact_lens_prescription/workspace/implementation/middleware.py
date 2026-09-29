"""Caller identity, RBAC, request parsing and referential lookup helpers.

Header names and role spellings come from PRD section 2.1:
    X-User-ID, X-User-Role
    Customer, Prescriber, ComplianceOfficer, FulfillmentOperator, PlatformAdmin
"""

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from db import db
from errors import ApiError

ROLE_CUSTOMER = "Customer"
ROLE_PRESCRIBER = "Prescriber"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_FULFILLMENT = "FulfillmentOperator"
ROLE_ADMIN = "PlatformAdmin"

ENTITY_BACKED_ROLES = (ROLE_CUSTOMER, ROLE_PRESCRIBER)

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_MMDD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")


# --------------------------------------------------------------------------- auth


def identity():
    """Step 1 of PRD section 2.10 -- caller identity present."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return str(user_id), str(role)


def require_role(role, allowed):
    """Step 3 of PRD section 2.10 -- role permitted for endpoint."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require_owner(role, user_id, owner_id, owner_role=ROLE_CUSTOMER):
    """Step 6 of PRD section 2.10 -- entity-backed ownership."""
    if role == owner_role and role in ENTITY_BACKED_ROLES:
        if owner_id is None or str(owner_id) != user_id:
            raise ApiError("ERR_IDENTITY_MISMATCH")


def require_prescriber_link(role, user_id, prescriber_id):
    """Prescriber ownership that tolerates rows carrying no prescriber at all."""
    if role == ROLE_PRESCRIBER and prescriber_id is not None and str(prescriber_id) != user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")


# ------------------------------------------------------------------- body parsing


def raw_body():
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = json.loads(data)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(name, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _coerce_int(name, value, rules):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    lo = rules.get("min")
    hi = rules.get("max")
    if lo is not None and value < lo:
        _bad(name, "is below the allowed minimum")
    if hi is not None and value > hi:
        _bad(name, "is above the allowed maximum")
    return value


def _coerce_decimal(name, value, rules):
    if isinstance(value, bool):
        _bad(name, "must be a number")
    if isinstance(value, (int, float)):
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            _bad(name, "must be a number")
    else:
        _bad(name, "must be a number")
    if not parsed.is_finite():
        _bad(name, "must be a finite number")
    lo = rules.get("min")
    hi = rules.get("max")
    if lo is not None and parsed < Decimal(str(lo)):
        _bad(name, "is below the allowed minimum")
    if hi is not None and parsed > Decimal(str(hi)):
        _bad(name, "is above the allowed maximum")
    places = rules.get("places", 2)
    return parsed.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _coerce_date(name, value):
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM-DD date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        _bad(name, "must be a valid calendar date")


def _coerce_timestamp(name, value):
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(name, "must be a valid ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def coerce_value(name, value, rules):
    kind = rules.get("type", "string")
    if kind == "string":
        if not isinstance(value, str):
            _bad(name, "must be a string")
        if rules.get("non_empty", True) and value.strip() == "":
            _bad(name, "must not be empty")
        return value
    if kind == "uuid":
        if not isinstance(value, str) or value.strip() == "":
            _bad(name, "must be an identifier string")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in rules["values"]:
            _bad(name, "is outside its declared domain")
        return value
    if kind == "int":
        return _coerce_int(name, value, rules)
    if kind == "bool":
        if not isinstance(value, bool):
            _bad(name, "must be a boolean")
        return value
    if kind == "decimal":
        return _coerce_decimal(name, value, rules)
    if kind == "date":
        return _coerce_date(name, value)
    if kind == "timestamp":
        return _coerce_timestamp(name, value)
    if kind == "int_array":
        if not isinstance(value, list):
            _bad(name, "must be an array of integers")
        out = []
        for element in value:
            if isinstance(element, bool) or not isinstance(element, int):
                _bad(name, "must contain only integers")
            if element < rules.get("min", 0):
                _bad(name, "contains an out-of-range value")
            out.append(element)
        return out
    if kind == "mmdd":
        if not isinstance(value, str) or not _MMDD.match(value.strip()):
            _bad(name, "must be an MM-DD anchor")
        return value.strip()
    _bad(name)


def parse_body(spec):
    """Step 2 of PRD section 2.10 -- request well-formed."""
    payload = raw_body()
    out = {}
    for name, rules in spec.items():
        present = name in payload and payload[name] is not None
        if not present:
            if rules.get("required"):
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
            out[name] = rules.get("default")
            continue
        out[name] = coerce_value(name, payload[name], rules)
    return out


def parse_query(spec=None):
    spec = spec or {}
    out = {}
    for name, rules in spec.items():
        if name not in request.args:
            out[name] = rules.get("default")
            continue
        text = request.args.get(name)
        kind = rules.get("type", "string")
        if kind == "int":
            if not re.match(r"^-?\d+$", text.strip()):
                _bad(name, "must be an integer")
            out[name] = _coerce_int(name, int(text.strip()), rules)
        elif kind == "bool":
            lowered = text.strip().lower()
            if lowered not in ("true", "false"):
                _bad(name, "must be a boolean")
            out[name] = lowered == "true"
        elif kind == "enum":
            if text not in rules["values"]:
                _bad(name, "is outside its declared domain")
            out[name] = text
        else:
            out[name] = text
    return out


def parse_pagination():
    values = parse_query(
        {
            "limit": {
                "type": "int",
                "min": PAGINATION_MIN_LIMIT,
                "max": PAGINATION_MAX_LIMIT,
                "default": PAGINATION_DEFAULT_LIMIT,
            },
            "offset": {"type": "int", "min": 0, "default": PAGINATION_DEFAULT_OFFSET},
        }
    )
    return values["limit"], values["offset"]


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, total


# ------------------------------------------------------------------ lookup helpers

_TABLES = {
    "insurance_plan": ("insurance_plans", "ERR_INSURANCE_PLAN_NOT_FOUND"),
    "product": ("products", "ERR_PRODUCT_NOT_FOUND"),
    "prescriber": ("prescribers", "ERR_PRESCRIBER_NOT_FOUND"),
    "customer": ("customers", "ERR_CUSTOMER_NOT_FOUND"),
    "prescription": ("prescriptions", "ERR_PRESCRIPTION_NOT_FOUND"),
    "verification_request": ("verification_requests", "ERR_VERIFICATION_REQUEST_NOT_FOUND"),
    "order": ("orders", "ERR_ORDER_NOT_FOUND"),
    "reorder_hold": ("reorder_holds", "ERR_REORDER_HOLD_NOT_FOUND"),
    "schedule": ("auto_reorder_schedules", "ERR_SCHEDULE_NOT_FOUND"),
    "return_request": ("return_requests", "ERR_RETURN_REQUEST_NOT_FOUND"),
    "claim": ("reimbursement_claims", "ERR_CLAIM_NOT_FOUND"),
    "dispute": ("prescriber_disputes", "ERR_DISPUTE_NOT_FOUND"),
}


def lookup(kind, row_id):
    table_name, error_id = _TABLES[kind]
    row = getattr(db, table_name).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row
