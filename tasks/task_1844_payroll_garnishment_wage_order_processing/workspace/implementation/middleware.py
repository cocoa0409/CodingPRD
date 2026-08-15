"""Auth (X-User-ID / X-User-Role), role authorization, body/field/pagination
helpers. Validation priority: auth -> role -> existence -> state -> business.
"""

import json

from flask import g, request

from errors import (
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    fail,
)
from util import parse_date, parse_instant

ROLES = (
    "employer_payroll_admin",
    "payroll_specialist",
    "payroll_manager",
    "compliance_auditor",
)

ROLE_ADMIN = "employer_payroll_admin"
ROLE_SPECIALIST = "payroll_specialist"
ROLE_MANAGER = "payroll_manager"
ROLE_AUDITOR = "compliance_auditor"

ALL_ROLES = ROLES


def authenticate():
    """Priority 1: both headers present and well-formed (known role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip():
        fail(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID header.")
    if role is None or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role header.")
    g.user_id = uid
    g.user_role = role


def authorize(*allowed_roles):
    """Priority 2: role permitted for the endpoint."""
    if g.user_role not in allowed_roles:
        fail(
            ERR_FORBIDDEN_ROLE,
            403,
            "Role '%s' is not permitted to perform this operation." % g.user_role,
        )


# --------------------------------------------------------------------------
# Request body / field validation (ERR_INVALID_REQUEST, 400)
# --------------------------------------------------------------------------

def get_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        fail(ERR_INVALID_REQUEST, 400, "Request body must be a valid JSON object.")
    if not isinstance(value, dict):
        fail(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return value


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key):
    if not _present(body, key):
        fail(ERR_INVALID_REQUEST, 400, "Missing required field '%s'." % key)
    if not isinstance(body[key], str) or not body[key]:
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be a non-empty string." % key)
    return body[key]


def opt_str(body, key, default=None):
    if not _present(body, key):
        return default
    if not isinstance(body[key], str):
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be a string." % key)
    return body[key]


def req_int(body, key):
    if not _present(body, key):
        fail(ERR_INVALID_REQUEST, 400, "Missing required field '%s'." % key)
    return _as_int(body[key], key)


def opt_int(body, key, default=None):
    if not _present(body, key):
        return default
    return _as_int(body[key], key)


def _as_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer." % key)
    return value


def req_number(body, key):
    if not _present(body, key):
        fail(ERR_INVALID_REQUEST, 400, "Missing required field '%s'." % key)
    return _as_number(body[key], key)


def opt_number(body, key, default=None):
    if not _present(body, key):
        return default
    return _as_number(body[key], key)


def _as_number(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be a number." % key)
    return value


def req_bool(body, key):
    if not _present(body, key):
        fail(ERR_INVALID_REQUEST, 400, "Missing required field '%s'." % key)
    if not isinstance(body[key], bool):
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be a boolean." % key)
    return body[key]


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        fail(
            ERR_INVALID_REQUEST,
            400,
            "Field '%s' must be one of %s." % (key, ", ".join(allowed)),
        )
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_date(body, key):
    raw = req_str(body, key)
    parsed = parse_date(raw)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    return raw


def req_instant(body, key):
    raw = req_str(body, key)
    parsed = parse_instant(raw)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be an ISO 8601 instant." % key)
    return raw


def req_object(body, key):
    if not _present(body, key):
        fail(ERR_INVALID_REQUEST, 400, "Missing required field '%s'." % key)
    if not isinstance(body[key], dict):
        fail(ERR_INVALID_REQUEST, 400, "Field '%s' must be an object." % key)
    return body[key]


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "Query parameter 'limit' must be an integer.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(ERR_INVALID_REQUEST, 400, "Query parameter 'offset' must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def public(rec):
    """Strip internal underscore-prefixed fields from a stored record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created(records):
    """Default list order: created_at ascending; sequence breaks ties (never id)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
