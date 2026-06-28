"""Request validation helpers (PRD §3.15, §2.3)."""
from datetime import datetime, timezone

from flask import request

from errors import (
    err,
    ERR_INVALID_REQUEST,
)


def get_body():
    """Parse JSON body; absent/invalid bodies are treated as empty dict.

    A malformed JSON payload is an ERR_INVALID_REQUEST.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length:
            data = request.get_json(silent=True)
            if data is None:
                raise err(ERR_INVALID_REQUEST, "Malformed or missing JSON body.")
            if not isinstance(data, dict):
                raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
            return data
        return {}
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string.")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a string.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean.")
    return v


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    return v


def parse_datetime(body, field):
    """Parse an ISO 8601 UTC datetime string from a body field."""
    raw = body.get(field)
    if not isinstance(raw, str) or raw == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime string.")
    return _parse_iso(raw, field)


def _parse_iso(raw, field):
    s = raw.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_value(raw, field):
    if not isinstance(raw, str) or raw == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime string.")
    return _parse_iso(raw, field)


def pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at asc (PRD §2.3), then apply offset/limit window."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
