"""Shared helpers: money math, validation primitives, pagination, audit log,
serialization, and common system-field management.
"""
import datetime
import re
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_REFERENCE_NOT_FOUND, ERR_NOT_FOUND,
)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def money(value):
    """Round to 2 dp using round-half-up; return a float for JSON output."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def to_decimal(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------
def get_body():
    """Parse JSON body; tolerate empty body for action endpoints."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, "malformed JSON body")
    if data is None:
        # Non-empty body that did not parse as JSON.
        raise APIError(ERR_INVALID_REQUEST, "malformed JSON body")
    if not isinstance(data, dict):
        raise APIError(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise APIError(ERR_INVALID_REQUEST, f"missing required field: {n}")


def require_str(body, name, allow_missing=False):
    if name not in body:
        if allow_missing:
            return None
        raise APIError(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be a non-empty string")
    return v


def require_enum(body, name, allowed, allow_missing=False, default=None):
    if name not in body or body[name] is None:
        if allow_missing:
            return default
        raise APIError(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    if v not in allowed:
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be one of {sorted(allowed)}")
    return v


def require_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be a boolean")
    return v


def require_number(body, name, allow_missing=False, default=None,
                   minimum=None, maximum=None, exclusive_min=False):
    if name not in body or body[name] is None:
        if allow_missing:
            return default
        raise APIError(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be a number")
    if exclusive_min:
        if minimum is not None and not (v > minimum):
            raise APIError(ERR_INVALID_REQUEST, f"field {name} must be > {minimum}")
    else:
        if minimum is not None and v < minimum:
            raise APIError(ERR_INVALID_REQUEST, f"field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be <= {maximum}")
    return v


def require_int(body, name, allow_missing=False, default=None, minimum=None):
    if name not in body or body[name] is None:
        if allow_missing:
            return default
        raise APIError(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be >= {minimum}")
    return v


def require_state_code(value, field="state_code"):
    if not isinstance(value, str) or not STATE_CODE_RE.match(value):
        raise APIError(ERR_INVALID_REQUEST, f"field {field} must match /^[A-Z]{{2}}$/")
    return value


def parse_dt(body, name, allow_missing=False):
    if name not in body or body[name] is None:
        if allow_missing:
            return None
        raise APIError(ERR_INVALID_REQUEST, f"missing required field: {name}")
    v = body[name]
    dt = parse_iso(v)
    if dt is None:
        raise APIError(ERR_INVALID_REQUEST, f"field {name} must be an ISO 8601 datetime")
    return dt


def parse_iso(value):
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


# ---------------------------------------------------------------------------
# FK resolution
# ---------------------------------------------------------------------------
def resolve_fk(collection, fk_id, label):
    """Resolve a body foreign key; raise ERR_REFERENCE_NOT_FOUND if missing."""
    rec = collection.get(fk_id)
    if rec is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"{label} not found: {fk_id}")
    return rec


def get_or_404(collection, rec_id, label="resource"):
    """Resolve a path-referenced resource; raise ERR_NOT_FOUND if missing."""
    rec = collection.get(rec_id)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, f"{label} not found: {rec_id}")
    return rec


# ---------------------------------------------------------------------------
# System fields
# ---------------------------------------------------------------------------
def stamp_create(rec, versioned=True):
    """Attach id/created_at (and updated_at/version when versioned)."""
    ts = db.now()
    rec["id"] = db.new_id()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at and bump version by exactly one."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Pagination + sorting
# ---------------------------------------------------------------------------
def pagination_params():
    """Read limit/offset query params with PRD defaults and bounds."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise APIError(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise APIError(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records, serialize):
    """Sort by created_at ascending (stable via _seq), paginate, serialize."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def append_audit(seller_id, subject_entity, subject_id, action):
    user_id, role = request.headers.get("X-User-ID"), request.headers.get("X-User-Role")
    entry = {
        "seller_id": seller_id,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "action": action,
        "actor_role": role,
        "actor_id": user_id,
    }
    stamp_create(entry, versioned=False)
    db.audit_log_entries[entry["id"]] = entry
    return entry
