"""Auth context extraction, role checks, body validation helpers."""

import json
from functools import wraps

from flask import request

import errors
from errors import ApiError

VALID_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")


def get_auth():
    """Priority 1: both headers present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise errors.err(errors.ERR_MISSING_USER_CONTEXT,
                         "X-User-ID and X-User-Role headers must be present and non-empty")
    return uid.strip(), role.strip()


def require_roles(*roles):
    """Decorator: priority 1 auth then priority 2 role authorization."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = get_auth()
            if role not in roles:
                raise errors.err(errors.ERR_FORBIDDEN_ROLE,
                                 f"Role {role} is not authorized for this endpoint")
            return fn(*args, _uid=uid, _role=role, **kwargs)
        return wrapper
    return deco


def get_json_body() -> dict:
    """Priority 2.7 (PRD layer 5): body well-formed. Bodies are objects; unknown
    fields are rejected by the per-endpoint field whitelist."""
    if not request.data:
        return {}
    try:
        body = json.loads(request.data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def check_fields(body: dict, required: dict, optional: dict) -> dict:
    """Validate presence and primitive types.

    required/optional map field name -> a type tag:
      'string'            non-empty string
      'string_nullable'   string or None
      'int'               integer (bool rejected), no range
      'int_nonneg'        integer >= 0
      'int_pos'           integer >= 1
      'number'            int/float (bool rejected)
      'bool'              boolean
      'datetime'          ISO 8601 datetime parseable
      'date'              YYYY-MM-DD date
      ('enum', values)    string in values
    Returns the coerced value dict (datetimes parsed).
    Raises ERR_INVALID_REQUEST for missing/unknown fields, ERR_VALIDATION for
    format/range/enum violations (PRD pipeline layers 5 then 6).
    """
    import db as _db

    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Unknown field: {key}")
    for key in required:
        if key not in body or body[key] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")

    out = {}
    for key, spec in list(required.items()) + list(optional.items()):
        if key not in body:
            continue
        val = body[key]
        if isinstance(spec, tuple) and spec and spec[0] == "enum":
            if not isinstance(val, str) or val not in spec[1]:
                raise errors.err(errors.ERR_VALIDATION,
                                 f"Field {key} must be one of {sorted(spec[1])}")
            out[key] = val
            continue
        if spec == "string":
            if not isinstance(val, str) or not val.strip():
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be a non-empty string")
            out[key] = val
        elif spec == "string_nullable":
            if val is not None and not isinstance(val, str):
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be a string")
            out[key] = val
        elif spec in ("int", "int_nonneg", "int_pos"):
            if isinstance(val, bool) or not isinstance(val, int):
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be an integer")
            if spec == "int_nonneg" and val < 0:
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be >= 0")
            if spec == "int_pos" and val < 1:
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be >= 1")
            out[key] = val
        elif spec == "number":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be a number")
            out[key] = val
        elif spec == "bool":
            if not isinstance(val, bool):
                raise errors.err(errors.ERR_VALIDATION, f"Field {key} must be a boolean")
            out[key] = val
        elif spec == "datetime":
            dt = _db.parse_iso(val)
            if dt is None:
                raise errors.err(errors.ERR_VALIDATION,
                                 f"Field {key} must be an ISO 8601 datetime")
            out[key] = dt
        elif spec == "date":
            if not _db.is_valid_date(val):
                raise errors.err(errors.ERR_VALIDATION,
                                 f"Field {key} must be a YYYY-MM-DD date")
            out[key] = val
        else:
            out[key] = val
    return out
