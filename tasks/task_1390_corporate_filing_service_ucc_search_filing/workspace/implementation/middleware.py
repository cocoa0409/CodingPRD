"""Auth-header extraction, role checks, ownership checks, body validation helpers
and pagination -- shared by every route.

Validation precedence (PRD section 2.9) is realized by the call order inside each
handler: (1) user context, (2) structural body validation, (3) role authorization,
(4) client ownership, (5) path existence, (6) body-reference existence,
(7) state/OCC, (8) safety, (9) temporal, (10) constraints, (11) fiscal.
"""
import re

from flask import request

import errors
from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "ClientManager",
    "FilingSpecialist",
    "FilingReviewer",
    "FilingOfficer",
    "SearchAnalyst",
}

_INT_RE = re.compile(r"^-?\d+$")


def auth():
    """Priority 1: X-User-ID and X-User-Role present, role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_missing_context()
    return user_id, role


def require_role(role, *allowed):
    """Priority 3: role permitted for this endpoint."""
    if role not in allowed:
        raise errors.err_unauthorized_role()


def check_client_ownership(role, user_id, client_id):
    """Priority 4: on client-scoped paths a ClientManager acts only on its own id."""
    if role == "ClientManager" and user_id != client_id:
        raise errors.err_ownership()


def body():
    """Parse the JSON request body. Absent body -> {}. Non-object JSON -> 400."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    data = None
    try:
        data = request.get_json(force=False, silent=True)
    except Exception:
        data = None
    if data is None:
        try:
            import json
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise errors.err_invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.err_invalid_request("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Structural field validators (priority 2)
# ---------------------------------------------------------------------------

def _present(data, name):
    return name in data and data[name] is not None


def as_int(value, name):
    """Coerce an integer field; accepts ints and digit strings, rejects bools/floats."""
    if isinstance(value, bool):
        raise errors.err_invalid_request(f"Field '{name}' must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _INT_RE.match(value.strip()):
        return int(value.strip())
    raise errors.err_invalid_request(f"Field '{name}' must be an integer")


def as_str(value, name):
    if not isinstance(value, str):
        raise errors.err_invalid_request(f"Field '{name}' must be a string")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise errors.err_invalid_request(
            f"Field '{name}' must be one of {sorted(allowed)}")
    return value


def as_str_list(value, name):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise errors.err_invalid_request(f"Field '{name}' must be an array of strings")
    return list(value)


def as_enum_list(value, name, allowed):
    if not isinstance(value, list):
        raise errors.err_invalid_request(f"Field '{name}' must be an array")
    out = []
    for v in value:
        out.append(as_enum(v, name, allowed))
    return out


def req_str(data, name):
    if not _present(data, name):
        raise errors.err_invalid_request(f"Missing required field: {name}")
    return as_str(data[name], name)


def opt_str(data, name, default=None):
    if not _present(data, name):
        return default
    return as_str(data[name], name)


def req_int(data, name):
    if not _present(data, name):
        raise errors.err_invalid_request(f"Missing required field: {name}")
    return as_int(data[name], name)


def opt_int(data, name, default=None):
    if not _present(data, name):
        return default
    return as_int(data[name], name)


def req_enum(data, name, allowed):
    if not _present(data, name):
        raise errors.err_invalid_request(f"Missing required field: {name}")
    return as_enum(data[name], name, allowed)


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return as_enum(data[name], name, allowed)


def pagination_params():
    """limit/offset query params: defaults 10/0, bounds [1,100] / [0,inf)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.err_invalid_request("offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
