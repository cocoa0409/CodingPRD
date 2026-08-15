"""Auth header extraction, role checking, request-body validation helpers."""

from datetime import datetime, timezone
from flask import request

import db as dbmod
import errors as E

ROLES = {"SponsorAdmin", "Pharmacist", "UnblindedPharmacist", "Monitor", "Investigator"}
ENTITY_BACKED = {"Pharmacist": False, "UnblindedPharmacist": True}


class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def can_see_arm_codes(self):
        return self.role in ("SponsorAdmin", "UnblindedPharmacist")


def require_auth():
    """Validate X-User-ID / X-User-Role headers per scaffold validations priority 1."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise E.unauthenticated()
    if role not in ROLES:
        raise E.unauthenticated()
    if role in ENTITY_BACKED:
        staff = dbmod.store.staff.get(user_id)
        if staff is None:
            raise E.unauthenticated()
        if staff.get("is_unblinded") != ENTITY_BACKED[role]:
            raise E.unauthenticated()
    return Ctx(user_id=user_id, role=role)


def require_role(ctx, allowed):
    if ctx.role not in allowed:
        raise E.unauthorized_role()


def body():
    """Return parsed JSON body or raise ERR_INVALID_REQUEST."""
    if not request.is_json:
        raise E.invalid_request("Request body must be JSON")
    try:
        data = request.get_json(force=False, silent=False)
    except Exception:
        raise E.invalid_request("Request body is not valid JSON")
    if data is None:
        raise E.invalid_request("Request body is missing")
    if not isinstance(data, dict):
        raise E.invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise E.invalid_request(f"Missing required field: {f}")


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
    if not isinstance(v, str):
        raise E.invalid_request(f"Field {field} must be a string")
    return v


def req_int(data, field):
    v = data.get(field)
    if v is None:
        raise E.invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise E.invalid_request(f"Field {field} must be an integer")
    return v


def req_number(data, field):
    v = data.get(field)
    if v is None:
        raise E.invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise E.invalid_request(f"Field {field} must be a number")
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


def parse_datetime(value, field):
    """Parse ISO 8601 datetime to aware datetime (UTC). Raises ERR_INVALID_REQUEST."""
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
    """Read limit/offset query params with scaffold defaults; invalid -> ERR_INVALID_REQUEST."""
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise E.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise E.invalid_request("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise E.invalid_request("offset must be an integer")
        if offset < 0:
            raise E.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending then apply limit/offset; returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda o: (o.get("created_at") or "", o.get("id") or ""))
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
