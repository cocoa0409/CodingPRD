"""Request parsing & structural validation helpers (priority 6)."""
from datetime import datetime, timezone

from flask import request

import errors
from db import db


def get_json_body():
    """Parse JSON body; tolerate empty body for no-input transition endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        # Could be malformed or absent. Treat absent as empty.
        if request.data.strip():
            raise errors.invalid_request("Malformed JSON body")
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_str(body, key):
    val = body.get(key)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field '{key}' is required and must be a non-empty string")
    return val


def require_int(body, key, minimum=None):
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{key}' is required and must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{key}' must be >= {minimum}")
    return val


def optional_int(body, key, default=0, minimum=None):
    if key not in body or body.get(key) is None:
        return default
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field '{key}' must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{key}' must be >= {minimum}")
    return val


def require_number(body, key, minimum=None):
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field '{key}' is required and must be a number")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field '{key}' must be >= {minimum}")
    return val


def require_enum(body, key, allowed):
    val = body.get(key)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field '{key}' must be one of {sorted(allowed)}")
    return val


def optional_bool(body, key, default=False):
    if key not in body or body.get(key) is None:
        return default
    val = body.get(key)
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field '{key}' must be a boolean")
    return val


def require_datetime(body, key):
    val = body.get(key)
    if not isinstance(val, str):
        raise errors.invalid_request(f"Field '{key}' is required and must be an ISO 8601 datetime string")
    parsed = parse_iso(val)
    if parsed is None:
        raise errors.invalid_request(f"Field '{key}' must be a valid ISO 8601 datetime")
    return val


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return parse_iso(db.clock)


# ---- Pagination (PRD §2.3) ----
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (tie-break by creation seq), then slice."""
    ordered = sorted(records, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
