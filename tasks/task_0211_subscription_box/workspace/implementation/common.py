"""Common resource scaffolding: audit fields, request parsing, validation helpers.

PRD §2.4: every primary resource carries id, created_at, updated_at, version.
WalletEntry is the lone exception (id + created_at only).
"""
from datetime import datetime, timezone
from flask import request

from db import db
from errors import err, ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import format_iso

DATETIME_FIELDS = {
    "created_at", "updated_at", "next_renewal_at", "paused_until",
    "cancelled_at", "cutoff_at", "ship_date", "charged_at",
}


def new_record(extra):
    """Create a primary resource dict with the standard audit set (PRD §2.4)."""
    ts = db.now()
    rec = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Mark a primary resource as mutated: refresh updated_at, bump version (PRD §2.4)."""
    rec["updated_at"] = db.now()
    rec["version"] = rec.get("version", 1) + 1


def serialize(rec):
    """Produce the public JSON representation: drop private keys, format datetimes."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if k in DATETIME_FIELDS and isinstance(v, datetime):
            out[k] = format_iso(v)
        else:
            out[k] = v
    return out


# ---- request body parsing -----------------------------------------------

def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
        return data
    return {}


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {name}.")
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string.")
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be an integer.")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be <= {maximum}.")
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(allowed)}.")
    return val


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 string.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- existence helpers (priority 3) -------------------------------------

def must_exist(collection, rid, label="resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, f"{label} not found.")
    return rec


# ---- pagination (PRD §2.3) ----------------------------------------------

def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit_v < 1 or limit_v > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset_v < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit_v, offset_v


def paginate(records):
    """Sort by created_at ascending (using _seq tiebreaker) and apply limit/offset."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
