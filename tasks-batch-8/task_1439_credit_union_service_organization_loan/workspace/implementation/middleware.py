"""Auth context, role checks, body parsing, datetime/field validators,
pagination, and the per-request `touch` helper for version bumps."""
from datetime import datetime, timezone

from flask import request, g

import db
from errors import APIError, raise_err, ERR_AUTH, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ROLES = {
    "NetworkAdmin",
    "TreasuryUser",
    "RegulatorUser",
    "CUSOOfficer",
    "OriginatorUser",
    "BuyerUser",
}

ALL_ROLES = sorted(ROLES)


def auth_context():
    """Validation priority 1: headers present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(
            ERR_AUTH,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def require_role(role, allowed):
    """Validation priority 2: caller role listed in the endpoint's roles."""
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role %s is not permitted on this endpoint" % role)


def body():
    """JSON object body; missing body treated as {} (action endpoints)."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Field validators (validation priority 5 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def req_present(b, field):
    if field not in b or b[field] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return b[field]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(b, field):
    v = req_present(b, field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return v


def opt_str(b, field):
    if field not in b or b[field] is None:
        return None
    if not isinstance(b[field], str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return b[field]


def req_int(b, field, minimum=None):
    v = req_present(b, field)
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    return v


def opt_int(b, field, default, minimum=None):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not is_int(v):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    return v


def req_enum(b, field, members):
    v = req_present(b, field)
    if not isinstance(v, str) or v not in members:
        raise_err(
            ERR_INVALID_REQUEST,
            "Field %s must be one of %s" % (field, ", ".join(sorted(members))),
        )
    return v


def opt_enum(b, field, members, default):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not isinstance(v, str) or v not in members:
        raise_err(
            ERR_INVALID_REQUEST,
            "Field %s must be one of %s" % (field, ", ".join(sorted(members))),
        )
    return v


def req_num(b, field):
    v = req_present(b, field)
    if not is_num(v):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def opt_num(b, field, default):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not is_num(v):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def req_bool(b, field):
    v = req_present(b, field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


def parse_dt_value(v, field):
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string" % field)
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, field):
    return parse_dt_value(req_present(b, field), field)


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit/offset, defaults 10/0, limit in 1..100
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if str(limit) != raw_limit.strip() and not raw_limit.strip().lstrip("+").isdigit():
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if str(offset) != raw_offset.strip() and not raw_offset.strip().lstrip("+").isdigit():
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, serializer):
    """items: full filtered list. Sorts by created_at asc (insertion-stable)."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return [serializer(e) for e in page], meta


# ---------------------------------------------------------------------------
# touch(): version bump + updated_at refresh, at most once per request/entity
# ---------------------------------------------------------------------------

def touch(kind, entity):
    touched = g.get("touched")
    if touched is None:
        touched = set()
        g.touched = touched
    key = (kind, entity["id"])
    if key in touched:
        return
    touched.add(key)
    entity["version"] += 1
    entity["updated_at"] = db.clock_now()
