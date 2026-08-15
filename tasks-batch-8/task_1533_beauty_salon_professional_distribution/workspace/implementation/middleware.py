"""Auth header extraction, role checking, request-body validation helpers."""

from datetime import datetime, timezone
from flask import request

import db as dbmod
import errors as E

ROLES = {"DistributionAdmin", "ComplianceOfficer", "SalesConsultant", "SalonBuyer", "WarehouseOperator"}
ENTITY_BACKED = {"SalesConsultant": "consultants", "SalonBuyer": "salons"}

ALL_ROLES = ROLES


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Pipeline step 1: X-User-ID / X-User-Role present, role declared,
    entity-backed ids resolvable."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise E.missing_context()
    if role not in ROLES:
        raise E.missing_context()
    if role in ENTITY_BACKED:
        coll = ENTITY_BACKED[role]
        if getattr(dbmod.store, coll).get(user_id) is None:
            raise E.missing_context()
    return Ctx(user_id=user_id, role=role)


def require_role(ctx, allowed):
    """Pipeline step 3."""
    if ctx.role not in allowed:
        raise E.unauthorized_role()


def body():
    """Return parsed JSON body as dict ({} when empty); raise ERR_INVALID_REQUEST otherwise."""
    raw = request.get_data()
    if not raw:
        return {}
    if not request.is_json:
        raise E.invalid_request("Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None:
        raise E.invalid_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise E.invalid_request("Request body must be a JSON object")
    return data


def empty_body():
    """For action endpoints with no declared inputs: no fields allowed."""
    data = body()
    if data:
        raise E.invalid_request("Unexpected request body fields: " + ", ".join(sorted(data)))
    return data


def no_unknown(data, allowed):
    for k in data:
        if k not in allowed:
            raise E.invalid_request(f"Unknown field: {k}")


def req_string(data, field):
    v = data.get(field)
    if v is None:
        raise E.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str) or v == "":
        raise E.invalid_request(f"Field {field} must be a non-empty string")
    return v


def opt_string(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v == "":
        raise E.invalid_request(f"Field {field} must be a non-empty string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None:
        raise E.invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.invalid_request(f"Field {field} must be an integer")
    return v


def req_pos_int(data, field):
    v = req_int(data, field)
    if v <= 0:
        raise E.invalid_request(f"Field {field} must be > 0")
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise E.invalid_request(f"Field {field} must be a boolean")
    return v


def req_enum(data, field, allowed):
    v = req_string(data, field)
    if v not in allowed:
        raise E.invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_str_array(data, field, non_empty=False):
    v = data.get(field)
    if v is None:
        raise E.invalid_request(f"Missing required field: {field}")
    if not isinstance(v, list):
        raise E.invalid_request(f"Field {field} must be an array")
    if non_empty and len(v) == 0:
        raise E.invalid_request(f"Field {field} must be a non-empty array")
    for el in v:
        if not isinstance(el, str) or el == "":
            raise E.invalid_request(f"Field {field} must contain non-empty strings")
    return v


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise E.invalid_request(f"Field {field} must be a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise E.invalid_request(f"Field {field} is not a parseable datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(data, field):
    if field not in data or data[field] is None:
        raise E.invalid_request(f"Missing required field: {field}")
    return parse_datetime(data[field], field)


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    raw = args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise E.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise E.invalid_request("limit must be between 1 and 100")
    raw = args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (ValueError, TypeError):
            raise E.invalid_request("offset must be an integer")
        if offset < 0:
            raise E.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, key=None):
    """Sort ascending (default: created_at then insertion order) and paginate."""
    limit, offset = parse_pagination()
    if key is None:
        items = sorted(items, key=dbmod.sort_key)
    else:
        items = sorted(items, key=key)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
