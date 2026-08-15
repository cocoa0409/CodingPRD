"""Parsing, validation, timestamp and pagination helpers."""

import re
import uuid
from datetime import datetime, timezone

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def new_id():
    """Server-minted UUID in canonical 8-4-4-4-12 text form (PRD 2.5)."""
    return str(uuid.uuid4())


def iso_z(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string; naive values are read as UTC."""
    if not isinstance(value, str) or not ISO_Z_RE.match(value.strip()):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def minute_floor(dt):
    """Datetime comparisons run at minute precision (PRD 2.9)."""
    return dt.replace(second=0, microsecond=0)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def get_path_or_404(store, entity_id):
    ent = store.get(entity_id)
    if ent is None:
        raise_err(ERR_NOT_FOUND, "Resource not found")
    return ent


def require_present(data, field):
    if field not in data or data[field] is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field '{field}'")
    return data[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a number")
    return value


def as_str(value, field):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a string")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise_err(
            ERR_INVALID_REQUEST,
            f"Field '{field}' must be one of {sorted(allowed)}",
        )
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return as_bool(data[field], field)


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return as_int(data[field], field)


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return as_str(data[field], field)


def parse_hhmm(value, field):
    if not isinstance(value, str) or not HHMM_RE.match(value):
        raise_err(ERR_INVALID_REQUEST, f"Field '{field}' must be HH:MM 24h time")
    hh, mm = value.split(":")
    return int(hh) * 60 + int(mm)


def pagination_args():
    """limit/offset per PRD 2.3: default 10/0, limit in 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def sorted_page(store_values, filters, limit, offset):
    """Filter (exact match on stored serialized keys), sort created_at asc
    (insertion order tie-break), then paginate."""
    rows = [r for r in store_values if all(r.get(k) == v for k, v in filters)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return rows[offset : offset + limit], total


def parse_query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise_err(ERR_INVALID_REQUEST, f"Query parameter '{name}' must be true or false")


def query_str(name):
    return request.args.get(name)
