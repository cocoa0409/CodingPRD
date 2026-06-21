"""Shared request parsing, pagination, and existence-lookup helpers."""
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import err

# Resource collection -> (store dict attr, not-found error id)
_LOOKUP = {
    "property": ("properties", "ERR_PROPERTY_NOT_FOUND"),
    "risk_assessment": ("risk_assessments", "ERR_RISK_ASSESSMENT_NOT_FOUND"),
    "inspector": ("inspectors", "ERR_INSPECTOR_NOT_FOUND"),
    "inspection": ("inspections", "ERR_INSPECTION_NOT_FOUND"),
    "application": ("applications", "ERR_APPLICATION_NOT_FOUND"),
    "endorsement": ("endorsements", "ERR_ENDORSEMENT_NOT_FOUND"),
    "quote": ("quotes", "ERR_QUOTE_NOT_FOUND"),
    "policy": ("policies", "ERR_POLICY_NOT_FOUND"),
    "payment": ("payments", "ERR_PAYMENT_NOT_FOUND"),
    "underwriter": ("underwriters", "ERR_UNDERWRITER_NOT_FOUND"),
}


def get_or_404(resource, rid):
    attr, error_id = _LOOKUP[resource]
    store = getattr(db, attr)
    rec = store.get(rid)
    if rec is None:
        raise err(error_id)
    return rec


def get_json_body():
    """Parse the JSON body; an unparseable body is ERR_INVALID_REQUEST."""
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return body
    return {}


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Out-of-range -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (insertion seq), slice, build list meta."""
    ordered = sorted(items, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    has_more = offset + limit < total
    list_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, list_meta


# ---- typed field extraction with ERR_INVALID_REQUEST on failure ----

def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}.")
    return body[name]


def as_string(value, name):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", f"{name} must be a non-empty string.")
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer.")
    return value


def as_number(value, name):
    """Accept int/float (not bool) and return a Decimal for exact arithmetic."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a number.")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a number.")


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"{name} must be a boolean.")
    return value


def as_enum(value, name, members):
    if value not in members:
        raise err("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(members)}.")
    return value
