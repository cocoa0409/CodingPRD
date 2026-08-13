"""Auth header extraction, role checking, request validation, pagination."""

import re
import uuid
from decimal import Decimal

from flask import request

import clock
import errors

ROLES = {"Customer", "Dispatcher", "BatchOperator", "Driver", "QCTech", "PlantManager"}

ALL_ROLES = ["PlantManager", "Dispatcher", "BatchOperator", "Driver", "QCTech", "Customer"]


def require_auth(allowed_roles):
    """Priority 1-2: X-User-ID / X-User-Role presence, role recognized, role allowed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_unauthenticated()
    if role not in allowed_roles:
        raise errors.err_forbidden()
    return user_id, role


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.err_validation("Request body must be a JSON object")
    return body


def new_uuid():
    return str(uuid.uuid4())


def new_record(common=True):
    rec = {"id": new_uuid(), "created_at": clock.iso(clock.now())}
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on every mutation."""
    rec["updated_at"] = clock.iso(clock.now())
    rec["version"] = rec.get("version", 1) + 1


def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_validation("limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_validation("offset must be an integer")
        if offset < 0:
            raise errors.err_validation("offset must be >= 0")
    return limit, offset


def sort_and_page(items, limit, offset):
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    return ordered[offset:offset + limit], len(ordered)


# ---------------------------------------------------------------- field checks

_BOOL = bool


def is_int(v):
    return isinstance(v, int) and not isinstance(v, _BOOL)


def is_number(v):
    return (isinstance(v, (int, float)) or isinstance(v, Decimal)) and not isinstance(v, _BOOL)


def dec(v):
    return Decimal(str(v))


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.err_validation(f"Missing required field: {name}")
    return body[name]


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise errors.err_validation(f"{name} must be a string")
    return v


def require_int(body, name):
    v = require_field(body, name)
    if not is_int(v):
        raise errors.err_validation(f"{name} must be an integer")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if not is_number(v):
        raise errors.err_validation(f"{name} must be a number")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, _BOOL):
        raise errors.err_validation(f"{name} must be a boolean")
    return v


def optional_number(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not is_number(v):
        raise errors.err_validation(f"{name} must be a number")
    return v


def optional_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, _BOOL):
        raise errors.err_validation(f"{name} must be a boolean")
    return v


def optional_string(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise errors.err_validation(f"{name} must be a string")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def require_date(body, name):
    v = require_string(body, name)
    if not _DATE_RE.match(v):
        raise errors.err_validation(f"{name} must be YYYY-MM-DD")
    return v


def require_month(body, name):
    v = require_string(body, name)
    if not _MONTH_RE.match(v):
        raise errors.err_validation(f"{name} must be YYYY-MM")
    return v


def require_hhmm(body, name):
    v = require_string(body, name)
    if not _HHMM_RE.match(v):
        raise errors.err_validation(f"{name} must be HH:MM (24h)")
    return v
