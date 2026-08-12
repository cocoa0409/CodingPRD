"""Auth, role, body parsing, deferred shape validation, pagination.

Validation pipeline ordering follows PRD §2.6: auth (1) -> role (2) ->
ownership (3) -> path resolution (4) -> body references (5) -> concurrency
(6) -> project-state gate (7) -> entity state (8) / terminal guard (9) ->
business rules (10-25) -> request shape (26, deliberately last).

Shape validators are therefore called at the END of each endpoint, after all
business checks have run against leniently-extracted raw values.
"""
from flask import request

from db import parse_date
from errors import fail

ROLES = {"PlatformAdmin", "Contractor", "Homeowner", "Subcontractor", "Inspector"}
ALL_ROLES = ("PlatformAdmin", "Contractor", "Homeowner", "Subcontractor", "Inspector")


def auth():
    """Priority 1: X-User-Role and X-User-ID headers present and well-formed."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None:
        fail("ERR_UNAUTHENTICATED", "Missing X-User-Role or X-User-ID header")
    if role not in ROLES or not uid.strip():
        fail("ERR_UNAUTHENTICATED", "Malformed X-User-Role or X-User-ID header")
    return role, uid.strip()


def require_role(role, *allowed):
    """Priority 2: role permitted for this endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this endpoint" % role)


def get_body():
    """Lenient JSON body parse. Malformed JSON / non-object -> ERR_INVALID_REQUEST."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def pagination():
    """limit default 10 (min 1, max 100), offset default 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if isinstance(limit, bool) or isinstance(offset, bool):
        fail("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


# ---------------------------------------------------------------------------
# Shape validators (priority 26): raise ERR_INVALID_REQUEST on bad shape.
# ---------------------------------------------------------------------------

def _missing(body, key):
    return key not in body or body.get(key) is None


def v_str(body, key, required=True):
    if _missing(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % key)
        return None
    if not isinstance(body[key], str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string" % key)
    return body[key]


def v_int(body, key, required=True):
    if _missing(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % key)
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % key)
    return val


def v_num(body, key, required=True):
    if _missing(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % key)
        return None
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number" % key)
    return val


def v_bool(body, key, required=True):
    if _missing(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % key)
        return None
    if not isinstance(body[key], bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % key)
    return body[key]


def v_arr(body, key, required=True):
    if _missing(body, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required" % key)
        return None
    if not isinstance(body[key], list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array" % key)
    return body[key]


def v_enum(body, key, allowed, required=True):
    val = v_str(body, key, required=required)
    if val is None:
        return None
    if val not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s" % (key, sorted(allowed)))
    return val


def v_date(body, key, required=True):
    val = v_str(body, key, required=required)
    if val is None:
        return None
    if parse_date(val) is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date (YYYY-MM-DD)" % key)
    return val


def v_item_object(item, what):
    if not isinstance(item, dict):
        fail("ERR_INVALID_REQUEST", "Each %s entry must be an object" % what)
