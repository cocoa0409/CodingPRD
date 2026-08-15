"""Shared helpers: timestamps, uuid, pagination, body-schema validation."""
import uuid
from datetime import datetime, timezone

from flask import request

import db
import errors


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def logical_now():
    """Current logical time as a datetime (UTC)."""
    return parse_dt(db.current_utc)


def logical_now_str():
    return db.current_utc


def wall_now_str():
    """Wall-clock timestamp with 3 fractional digits, for created_at/updated_at."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 string into an aware datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_valid_dt(s):
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with Z suffix, second precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_months(dt, months):
    """Add (or subtract) calendar months to a datetime."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    # days in target month
    if m == 12:
        next_month = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    this_month = datetime(y, m, 1, tzinfo=timezone.utc)
    dim = (next_month - this_month).days
    d = min(dt.day, dim)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Identity / mutation bookkeeping
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Bump version and refresh updated_at on a mutated resource."""
    entity["version"] += 1
    entity["updated_at"] = wall_now_str()


def new_resource(fields):
    """Create the common system-managed fields around an initial field set."""
    now = wall_now_str()
    r = {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}
    r.update(fields)
    return r


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def get_pagination():
    """Parse limit/offset query params with defaults; 400 on invalid."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except ValueError:
            raise errors.err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_validation("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except ValueError:
            raise errors.err_validation("offset must be an integer")
        if offset < 0:
            raise errors.err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending and slice."""
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Body schema validation
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON body as a dict; raise ERR_VALIDATION if not an object."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.err_validation("Request body must be a JSON object")
    return body


def validate_body(body, spec):
    """Validate body against a field spec.

    spec: list of (name, kind, required) where kind is one of:
      'string', 'int', 'bool', 'array', 'datetime', 'enum:A,B,C'
    Raises ERR_VALIDATION on any violation.
    """
    declared = {name for name, _, _ in spec}
    for key in body:
        if key not in declared:
            raise errors.err_validation(f"Undeclared field: {key}")
    for name, kind, required in spec:
        if name not in body:
            if required:
                raise errors.err_validation(f"Missing required field: {name}")
            continue
        val = body[name]
        if val is None and not required:
            continue
        _check_type(name, val, kind)


def _check_type(name, val, kind):
    if kind == "string":
        if not isinstance(val, str):
            raise errors.err_validation(f"Field {name} must be a string")
    elif kind == "int":
        if not isinstance(val, int) or isinstance(val, bool):
            raise errors.err_validation(f"Field {name} must be an integer")
    elif kind == "bool":
        if not isinstance(val, bool):
            raise errors.err_validation(f"Field {name} must be a boolean")
    elif kind == "array":
        if not isinstance(val, list):
            raise errors.err_validation(f"Field {name} must be an array")
    elif kind == "datetime":
        if not is_valid_dt(val):
            raise errors.err_validation(f"Field {name} must be an ISO 8601 datetime")
    elif kind.startswith("enum:"):
        members = kind[5:].split(",")
        if val not in members:
            raise errors.err_validation(
                f"Field {name} must be one of {', '.join(members)}")
    else:
        raise AssertionError(f"unknown kind {kind}")
