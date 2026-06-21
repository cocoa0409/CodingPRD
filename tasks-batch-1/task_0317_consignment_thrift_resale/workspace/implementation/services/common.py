"""Common entity helpers: timestamps, system fields, pagination, type checks."""
from datetime import datetime, timezone

from db import store, new_id
from errors import err


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now():
    return store.clock.now()


def base_record(versioned=True):
    """Build the system-managed common quartet for a new record."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": iso(ts),
        "_created_seq": store.next_seq(),
        "_created_dt": ts,
    }
    if versioned:
        rec["updated_at"] = iso(ts)
        rec["version"] = 1
    return rec


def ledger_record():
    """Append-only records carry only id + created_at (PRD §2.4)."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": iso(ts),
        "_created_seq": store.next_seq(),
        "_created_dt": ts,
    }


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4 / §2.9)."""
    rec["updated_at"] = iso(now())
    rec["version"] = rec.get("version", 1) + 1


def public(rec, hidden=None):
    """Strip private bookkeeping keys (those beginning with '_') for output."""
    hidden = hidden or set()
    return {k: v for k, v in rec.items() if not k.startswith("_") and k not in hidden}


# ---- request body / type validation -----------------------------------------

def require_body():
    from flask import request
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return body
    return {}


def require_str(body, key, allow_empty=False):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % key)
    val = body[key]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % key)
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "%s must be non-empty" % key)
    return val


def require_int(body, key, minimum=None):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (key, minimum))
    return val


def require_enum(body, key, allowed, default=None):
    if key not in body or body[key] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", "Missing field: %s" % key)
    val = body[key]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, sorted(allowed)))
    return val


EMAIL_LOCAL = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._%+-")


def valid_email(value):
    if not isinstance(value, str) or value.strip() == "":
        return False
    if value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    return True


# ---- pagination --------------------------------------------------------------

def parse_pagination():
    from flask import request
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit out of bounds [1,100]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0")

    return limit, offset


def sort_by_created(records):
    return sorted(records, key=lambda r: r["_created_seq"])


def page(records, limit, offset):
    ordered = sort_by_created(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
