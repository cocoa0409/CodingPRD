"""Auth header extraction, role checking, request validation, pagination, serialization."""

import re
import uuid
from datetime import date, datetime

from flask import request

import clock
import errors
from db import next_seq, stores

ROLES = {
    "GalaAdmin",
    "ProcurementOfficer",
    "ValuationApprover",
    "CatalogManager",
    "FinanceOfficer",
    "Bidder",
    "Donor",
}

ALL_ROLES = [
    "GalaAdmin",
    "ProcurementOfficer",
    "ValuationApprover",
    "CatalogManager",
    "FinanceOfficer",
    "Bidder",
    "Donor",
]


def require_auth(allowed_roles):
    """Priorities 1-2: X-User-ID / X-User-Role present, role recognized, role allowed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_unauthenticated()
    if role not in allowed_roles:
        raise errors.err_unauthorized_role()
    return user_id, role


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object")
    return body


def new_uuid():
    return str(uuid.uuid4())


def new_record():
    """Common resource properties (PRD 2.4) stamped from the logical clock (PRD 2.5)."""
    now = clock.now()
    return {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Refresh updated_at and bump version on every mutation (incl. cascades, PRD 2.4)."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1


_THREE_DIGIT_FIELDS = {"created_at", "updated_at"}


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = clock.iso3(v) if k in _THREE_DIGIT_FIELDS else clock.fmt(v)
        else:
            out[k] = v
    return out


def get_or_404(store, rid):
    rec = stores[store].get(rid)
    if rec is None:
        raise errors.err_not_found(f"{store} id {rid!r} does not exist")
    return rec


def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_invalid_request("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.err_invalid_request("offset must be >= 0")
    return limit, offset


def sort_and_page(items, limit, offset):
    """Default list ordering: created_at ascending (PRD 2.3), insertion-sequence tie-break."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    return ordered[offset:offset + limit], len(ordered)


# ---------------------------------------------------------------- field checks

_BOOL = bool


def is_int(v):
    return isinstance(v, int) and not isinstance(v, _BOOL)


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.err_invalid_request(f"Missing required field: {name}")
    return body[name]


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"{name} must be a string")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if not is_int(v):
        raise errors.err_invalid_request(f"{name} must be an integer")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, _BOOL):
        raise errors.err_invalid_request(f"{name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = require_string(body, name)
    if v not in allowed:
        raise errors.err_invalid_request(f"{name} must be one of {sorted(allowed)}")
    return v


def require_datetime(body, name):
    v = require_string(body, name)
    try:
        return clock.parse(v)
    except (ValueError, TypeError):
        raise errors.err_invalid_request(f"{name} must be an ISO 8601 datetime")


def optional_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"{name} must be a string")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_date(body, name):
    v = require_string(body, name)
    if not _DATE_RE.match(v):
        raise errors.err_invalid_request(f"{name} must be YYYY-MM-DD")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise errors.err_invalid_request(f"{name} must be a valid calendar date")
    return v
