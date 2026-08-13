"""Auth header extraction, role checking, and request-body field validators.

Validation pipeline layer 1 (auth) and layer 2 (role authorization) live here,
plus the layer-3 payload well-formedness helpers.
"""

import json
import re
from datetime import date

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
)

ROLES = [
    "SustainabilityManager",
    "VendorUser",
    "DataSteward",
    "WasteAuditor",
    "CertificationOfficer",
]

ALL_ROLES = list(ROLES)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def authenticate(allowed_roles):
    """Layer 1 + 2: headers present/valid role; role permitted on endpoint."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "X-User-ID / X-User-Role header missing or role not declared")
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "Role is not permitted to call this endpoint")
    return uid, role


def get_body():
    """Parse the JSON request body into a dict. Empty body -> {}."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    try:
        val = json.loads(raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body is not valid JSON")
    if not isinstance(val, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return val


def check_unknown(b, allowed):
    unknown = [k for k in b.keys() if k not in allowed]
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Unknown field(s): {', '.join(sorted(unknown))}")


def no_input(b):
    """Endpoints declared with no input reject any supplied field."""
    if b:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "This endpoint does not accept a request body")


_MISSING = object()


def _fetch(b, k, required, nullable=False):
    v = b.get(k, _MISSING)
    if v is _MISSING:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {k}")
        return None
    if v is None:
        if nullable or not required:
            return None
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} may not be null")
    return v


def f_str(b, k, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} must be a string")
    return v


def f_int(b, k, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} must be an integer")
    return v


def f_num(b, k, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} must be a number")
    return v


def f_bool(b, k, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {k} must be a boolean")
    return v


def f_enum(b, k, values, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if not isinstance(v, str) or v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {k} must be one of: {', '.join(values)}")
    return v


def f_date(b, k, required=True, nullable=False):
    v = _fetch(b, k, required, nullable)
    if v is None:
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {k} must be an ISO date (YYYY-MM-DD)")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {k} must be an ISO date (YYYY-MM-DD)")
    return v


def f_pct(b, k, required=True, nullable=False):
    """contamination_pct: number within 0..100 inclusive."""
    v = f_num(b, k, required=required, nullable=nullable)
    if v is None:
        return None
    if v < 0 or v > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {k} must be between 0 and 100")
    return v
