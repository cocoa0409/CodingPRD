"""Authentication, role authorisation, ownership and request parsing."""

import json

from flask import request

import db
from errors import ApiError

ROLES = (
    "Manufacturer",
    "Retailer",
    "IntakeClerk",
    "FraudAnalyst",
    "SettlementOfficer",
    "ClearinghouseAdmin",
)

ALL_ROLES = list(ROLES)

# Roles that are backed by a stored entity row (X-User-ID is that row's id).
ENTITY_BACKED = ("Manufacturer", "Retailer")


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Ladder level 1 then level 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognised role '%s'" % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role
        )
    return Ctx(str(user_id).strip(), role)


# --------------------------------------------------------------------------
# ownership (ladder level 4)
# --------------------------------------------------------------------------

def own_retailer(ctx, retailer_id):
    if ctx.role == "Retailer" and ctx.user_id != retailer_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Retailer does not own this resource"
        )


def own_manufacturer(ctx, manufacturer_id):
    if ctx.role == "Manufacturer" and ctx.user_id != manufacturer_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Manufacturer does not own this resource"
        )


# --------------------------------------------------------------------------
# request body
# --------------------------------------------------------------------------

def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        offset = _as_int(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset


def _as_int(raw, name):
    text = str(raw).strip()
    if text == "" or not (text.isdigit() or (text.startswith("-") and text[1:].isdigit())):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return int(text)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def bool_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name)


def str_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return str(raw)


def fetch(collection, row_id, error_id):
    row = getattr(db.db, collection).get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row
