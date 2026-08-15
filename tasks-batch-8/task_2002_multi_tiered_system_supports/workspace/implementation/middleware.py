"""Auth middleware and helpers: header extraction, role checking, validation helpers."""

import re
import uuid
from datetime import datetime

from flask import request

from clock import now_iso_ms
from db import DB
from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
)

# The seven operational roles per PRD §2.1. "Any" is a documentation marker for
# read-only endpoints, not an assignable role value.
ROLES = {
    "PlatformAdmin",
    "DistrictCoordinator",
    "SchoolRegistrar",
    "Teacher",
    "InterventionistRole",
    "TeamLead",
    "SpEdDirector",
}

ALL_ROLES = (
    "PlatformAdmin",
    "DistrictCoordinator",
    "SchoolRegistrar",
    "Teacher",
    "InterventionistRole",
    "TeamLead",
    "SpEdDirector",
)


def require_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing or malformed",
        )
    return user_id, role


def require_role(*roles):
    user_id, role = require_auth()
    if role not in roles:
        raise err(ERR_INSUFFICIENT_PERMISSIONS, 403, "Role not permitted for this operation")
    return user_id, role


# ---------- generic request-body validation ----------

def get_json_body():
    if not request.is_json:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def check_unknown_fields(body, allowed):
    for k in body.keys():
        if k not in allowed:
            raise err(ERR_INVALID_REQUEST, 400, f"Unknown field: {k}")


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def req_string(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string")
    return v


def opt_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string")
    return v


def _coerce_int(v, name):
    if isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")


def req_int(body, name):
    v = body.get(name)
    if v is None:
        raise err(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return _coerce_int(v, name)


def opt_int(body, name):
    v = body.get(name)
    if v is None:
        return None
    return _coerce_int(v, name)


def req_enum(body, name, choices):
    v = body.get(name)
    if not isinstance(v, str) or v not in choices:
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be one of {sorted(choices)}")
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


def opt_bool(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a boolean")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def req_date(body, name):
    v = body.get(name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an ISO date string (YYYY-MM-DD)")
    try:
        parse_date(v)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be a valid calendar date")
    return v


def opt_date(body, name):
    v = body.get(name)
    if v is None:
        return None
    return req_date(body, name)


def req_enum_array(body, name, choices):
    v = body.get(name)
    if not isinstance(v, list):
        raise err(ERR_INVALID_REQUEST, 400, f"Field {name} must be an array")
    for item in v:
        if not isinstance(item, str) or item not in choices:
            raise err(ERR_INVALID_REQUEST, 400, f"Field {name} elements must be in {sorted(choices)}")
    return list(v)


def opt_enum_array(body, name, choices, default=None):
    v = body.get(name)
    if v is None:
        return default
    return req_enum_array(body, name, choices)


# ---------- entity helpers ----------

def new_id():
    return str(uuid.uuid4())


def base_fields():
    """Common fields for entities carrying created_at/updated_at/version (PRD §2.6)."""
    ts = now_iso_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }


def base_fields_append_only():
    """Immutable/append-only entities carry only id and created_at (PRD §2.6)."""
    return {
        "id": new_id(),
        "created_at": now_iso_ms(),
        "_seq": DB.next_seq(),
    }


def touch(entity):
    """Bump updated_at and version for a mutation (§2.6: derived-field changes count)."""
    entity["updated_at"] = now_iso_ms()
    entity["version"] += 1


def paginate(items):
    """Apply limit/offset per PRD §2.3 (defaults 10/0, min 1, max 100)."""
    q = request.args
    limit_raw = q.get("limit")
    offset_raw = q.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_created(items):
    """Default list ordering: created_at ascending (PRD §2.3), _seq tie-break."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
