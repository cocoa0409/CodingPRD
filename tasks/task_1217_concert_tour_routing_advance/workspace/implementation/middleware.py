"""Auth header extraction, role checking, body parsing and field validators.

Auth (SCAFFOLD validations priority 1-2 / PRD 2.1):
  - X-User-ID and X-User-Role must both be present and well-formed
    (else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400).
  - Role must be permitted for the operation
    (else ERR_INSUFFICIENT_PERMISSIONS, 403).
  Roles are spelled exactly: TourManager, Promoter, VenueRep,
  SettlementAccountant, Any.
"""
import json
from datetime import datetime, timezone

from flask import request

from errors import ApiError

ROLE_TOUR_MANAGER = "TourManager"
ROLE_PROMOTER = "Promoter"
ROLE_VENUE_REP = "VenueRep"
ROLE_ACCOUNTANT = "SettlementAccountant"
ROLE_ANY = "Any"

ROLES = (ROLE_TOUR_MANAGER, ROLE_PROMOTER, ROLE_VENUE_REP, ROLE_ACCOUNTANT, ROLE_ANY)
# All list/get endpoints are available to any authenticated actor (PRD 2.1 "Any").
READ_ROLES = frozenset(ROLES)


def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Role not authorized for this operation",
        )
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing and typed field validators -> ERR_INVALID_REQUEST (400)
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON object body, or {} when no body was sent.

    Malformed JSON or a non-object payload is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        b = json.loads(request.data)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed JSON body")
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def _missing(name):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {name}")


def _bad_type(name, want):
    raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be {want}")


def v_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, str) or v == "":
        _bad_type(name, "a non-empty string")
    return v


def v_int(body, name, required=True, minv=None, maxv=None):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _bad_type(name, "an integer")
    if minv is not None and v < minv:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be >= {minv}")
    if maxv is not None and v > maxv:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be <= {maxv}")
    return v


def v_bool(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, bool):
        _bad_type(name, "a boolean")
    return v


def v_enum(body, name, allowed, required=True):
    v = v_str(body, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            f"Field {name} must be one of {sorted(allowed)}",
        )
    return v


def parse_date(s):
    """Strict YYYY-MM-DD -> datetime.date, or None."""
    if not isinstance(s, str):
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
    if d.isoformat() != s:
        return None
    return d


def parse_dt(s):
    """ISO-8601 timestamp (Z or offset) -> aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def fmt_dt(d):
    """ISO 8601 UTC with three fractional digits and a Z suffix."""
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def v_date(body, name, required=True):
    """Validate a date field; returns a datetime.date."""
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    d = parse_date(v)
    if d is None:
        _bad_type(name, "an ISO date (YYYY-MM-DD)")
    return d


def v_dt(body, name, required=True):
    """Validate a timestamp field; returns an aware UTC datetime."""
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    d = parse_dt(v)
    if d is None:
        _bad_type(name, "an ISO-8601 timestamp")
    return d


def v_date_list(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            _missing(name)
        return None
    if not isinstance(v, list):
        _bad_type(name, "an array of ISO dates")
    out = []
    for item in v:
        d = parse_date(item)
        if d is None:
            _bad_type(name, "an array of ISO dates (YYYY-MM-DD)")
        out.append(d.isoformat())
    return out
