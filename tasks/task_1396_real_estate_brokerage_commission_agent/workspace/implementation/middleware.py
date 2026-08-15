"""Auth middleware and validation helpers (PRD §2.1, §2.9).

Guard evaluation order (the first failing guard wins):
  1. Header presence            -> ERR_MISSING_USER_CONTEXT (400)
  2. Role admission             -> ERR_FORBIDDEN_FOR_ROLE (403)
  3. Agent identity resolution  -> ERR_UNKNOWN_USER_IDENTITY (403)
  4. Agent ownership scoping    -> ERR_FORBIDDEN_RESOURCE (403)
  5. Request schema             -> ERR_INVALID_REQUEST (400)
  6. Path existence             -> ERR_NOT_FOUND (404)
  7. OCC                        -> ERR_STALE_* (412)
  8. State validity             -> 409 family
  ...
"""

from flask import request

import db
from errors import (
    ApiError, ERR_MISSING_USER_CONTEXT, ERR_FORBIDDEN_FOR_ROLE,
    ERR_UNKNOWN_USER_IDENTITY, ERR_FORBIDDEN_RESOURCE, ERR_INVALID_REQUEST,
)

ROLES = {"BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Agent", "Auditor"}

# Role lists per endpoint are attached to each route via @guard(roles=[...]).
READ_ROLES = ["BrokerAdmin", "OfficeManager", "TransactionCoordinator", "Auditor", "Agent"]
TRUST_READ_ROLES = ["BrokerAdmin", "OfficeManager", "Auditor"]


def get_context():
    """Steps 1-3 of the guard gauntlet. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_MISSING_USER_CONTEXT, 400,
                       "X-User-ID and X-User-Role headers must both be present and non-empty")
    return user_id, role


def require_roles(role, roles):
    """Step 2: role admission."""
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, 403,
                       "caller role %s is not admitted to this endpoint" % role)


def resolve_agent_identity(user_id, role):
    """Step 3: when role == Agent, X-User-ID must be an existing Agent."""
    if role == "Agent":
        if user_id not in db.agents:
            raise ApiError(ERR_UNKNOWN_USER_IDENTITY, 403,
                           "X-User-ID does not identify an existing Agent")


def forbid_unless_owner(role, user_id, owner_agent_id):
    """Step 4: Agent-role callers may only touch resources they own."""
    if role == "Agent" and owner_agent_id != user_id:
        raise ApiError(ERR_FORBIDDEN_RESOURCE, 403,
                       "Agent-role caller may only touch their own resources")


# ---------------- request-body schema helpers (step 5) ----------------

def body():
    """JSON body that must be an object when present."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s is required and must be a string" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a string or null" % field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s is required and must be an integer" % field)
    return v


def opt_int(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be an integer" % field)
    return v


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_num(data, field):
    v = data.get(field)
    if not _is_num(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s is required and must be a number" % field)
    return v


def opt_num(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not _is_num(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a number" % field)
    return v


def req_date(data, field):
    from timeutil import parse_date
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s is required and must be a YYYY-MM-DD date" % field)
    try:
        return parse_date(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a valid YYYY-MM-DD date" % field)


def opt_date(data, field, default=None):
    from timeutil import parse_date
    v = data.get(field, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a YYYY-MM-DD date" % field)
    try:
        return parse_date(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a valid YYYY-MM-DD date" % field)


def parse_pagination():
    """limit/offset query params (PRD §2.3): default 10/0, min 1, max 100."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def parse_enum_filter(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid value for filter %s" % name)
    return v


def parse_str_filter(name):
    return request.args.get(name)


def parse_int_filter(name):
    v = request.args.get(name)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "filter %s must be an integer" % name)
