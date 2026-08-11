"""Payload field helpers. Error semantics:

- absent / null required field            -> ERR_MISSING_REQUIRED_FIELD (400)
- malformed value (bad enum, bad datetime,
  wrong type, bad window order, etc.)     -> ERR_VALIDATION (400)
"""
from flask import request

import errors
from util import parse_dt


def payload():
    """Return the request JSON object; an absent/unparseable body reads as {}."""
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def need(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    return v


def need_str(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    if not isinstance(v, str) or not v.strip():
        errors.validation(f"field {name} must be a non-empty string")
    return v


def opt_str(p, name):
    v = p.get(name, None)
    if v is None:
        return None
    if not isinstance(v, str):
        errors.validation(f"field {name} must be a string")
    return v


def need_enum(p, name, allowed):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    if v not in allowed:
        errors.validation(f"field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(p, name, allowed):
    v = p.get(name, None)
    if v is None:
        return None
    if v not in allowed:
        errors.validation(f"field {name} must be one of {sorted(allowed)}")
    return v


def need_bool(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    if not isinstance(v, bool):
        errors.validation(f"field {name} must be a boolean")
    return v


def opt_bool(p, name, default=False):
    v = p.get(name, None)
    if v is None:
        return default
    if not isinstance(v, bool):
        errors.validation(f"field {name} must be a boolean")
    return v


def _coerce_int(v, name):
    if isinstance(v, bool):
        errors.validation(f"field {name} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("-").isdigit():
            return int(s)
    errors.validation(f"field {name} must be an integer")


def need_int(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    return _coerce_int(v, name)


def opt_int(p, name):
    v = p.get(name, None)
    if v is None:
        return None
    return _coerce_int(v, name)


def need_dt(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    dt = parse_dt(v)
    if dt is None:
        errors.validation(f"field {name} must be an ISO8601 datetime")
    return dt


def opt_dt(p, name):
    v = p.get(name, None)
    if v is None:
        return None
    dt = parse_dt(v)
    if dt is None:
        errors.validation(f"field {name} must be an ISO8601 datetime")
    return dt


def need_list(p, name):
    v = p.get(name, None)
    if v is None:
        errors.missing_field(name)
    if not isinstance(v, list):
        errors.validation(f"field {name} must be an array")
    return v


def occ_version(p):
    """expected_case_version is mandatory on the three create-with-supersede
    endpoints (PRD §2.7); values may arrive as JSON ints or digit strings."""
    v = p.get("expected_case_version", None)
    if v is None:
        errors.missing_field("expected_case_version")
    return _coerce_int(v, "expected_case_version")


def parse_pagination(args):
    """limit (default 10, clamped to [1, 100]) and offset (default 0, >= 0)."""
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.validation("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.validation("offset must be an integer")
        offset = max(0, offset)
    return limit, offset
