"""Authentication, RBAC, request well-formedness and pagination (PRD 2.1, 2.3, 2.5 rank 1/2/5/6)."""
import re
from datetime import date

from flask import request

from core import ApiError, fail, dec

ROLES = (
    "NetworkStrategist",
    "ConsolidationApprover",
    "ComplianceOfficer",
    "HRPartner",
    "RealEstateManager",
    "BranchManager",
    "NetworkOpsAdmin",
)

ALL_ROLES = list(ROLES)

_MISSING = object()


# --------------------------------------------------------------------------- #
# rank 1 / rank 2
# --------------------------------------------------------------------------- #
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a recognised role." % role)
    return user_id, role


def authorize(allowed_roles):
    """rank 1 then rank 2.  Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)
    return user_id, role


def require_branch_ownership(user_id, role, branch_id):
    """rank 5 - evaluated before path resolution, so no lookup happens here."""
    if role == "BranchManager" and user_id != branch_id:
        fail("ERR_BRANCH_OWNERSHIP_REQUIRED", "A BranchManager may only act on their own branch.")


# --------------------------------------------------------------------------- #
# rank 6 - request well-formedness
# --------------------------------------------------------------------------- #
def json_body(required=True):
    if not request.data:
        if required:
            return {}
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_int(body, name, minimum=None, maximum=None, required=True, default=_MISSING):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (name, maximum))
    return value


def req_bool(body, name, required=True, default=_MISSING):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_str(body, name, min_len=1, max_len=None, pattern=None, required=True, default=_MISSING):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d characters." % (name, max_len))
    if pattern is not None and not re.fullmatch(pattern, value):
        fail("ERR_INVALID_REQUEST", "Field '%s' does not match the required format." % name)
    return value


def req_enum(body, name, allowed, required=True, default=_MISSING):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_date(body, name, required=True, default=_MISSING):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 date (YYYY-MM-DD)." % name)
    try:
        date.fromisoformat(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid calendar date." % name)
    return value


def req_miles(body, name, low=0.0, high=60.0, required=True, default=_MISSING):
    """Genuine decimal input with at most one decimal place (PRD 2.7)."""
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None if default is _MISSING else default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    d = dec(value)
    if d.as_tuple().exponent < -1:
        fail("ERR_INVALID_REQUEST", "Field '%s' accepts at most one decimal place." % name)
    if d < dec(low) or d > dec(high):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be between %s and %s." % (name, low, high))
    return float(d)


def req_instant(body, name, required=True):
    if not _present(body, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return None
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant string." % name)
    from datetime import datetime, timezone
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Pagination + query filters (PRD 2.3)
# --------------------------------------------------------------------------- #
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        if not re.fullmatch(r"-?\d+", raw or ""):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        if not re.fullmatch(r"-?\d+", raw or ""):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_value(name, allowed=None):
    args = request.args
    if name not in args:
        return None
    value = args.get(name)
    if value == "":
        return None
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_bool(name):
    args = request.args
    if name not in args or args.get(name) == "":
        return None
    value = args.get(name)
    low = value.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def window(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
