"""Shared helpers: datetime parsing, pagination, field bumping."""
from datetime import datetime, timezone

from errors import err, ERR_VALIDATION
import db


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Accepts trailing 'Z'. Raises ERR_VALIDATION on malformed input.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise err(ERR_VALIDATION, f"{field} is not a valid ISO 8601 datetime")
    else:
        raise err(ERR_VALIDATION, f"{field} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    """Parse a date-or-datetime string into a tz-aware UTC datetime (for birthdate)."""
    return parse_dt(value, field)


def require(body, field):
    if body is None or field not in body or body[field] is None:
        raise err(ERR_VALIDATION, f"missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or len(v) == 0:
        raise err(ERR_VALIDATION, f"{field} must be a non-empty string")
    return v


def require_int(body, field, minimum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_VALIDATION, f"{field} must be >= {minimum}")
    return v


def require_enum(body, field, choices):
    v = require(body, field)
    if v not in choices:
        raise err(ERR_VALIDATION, f"{field} must be one of {sorted(choices)}")
    return v


def optional_bool(body, field, default=False):
    if body is None or field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, f"{field} must be a boolean")
    return v


def parse_pagination(args):
    """Parse limit/offset query params (PRD §2.3). limit default 10, min 1, max 100;
    offset default 0."""
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") is not None and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") is not None and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    """Sort by created_at ASC (tie-break insertion seq) then page (PRD §2.3)."""
    ordered = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.5)."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1
