"""Shared helpers: timestamps, datetime parsing, body validation, pagination,
serialization, and the round-half-up primitive (PRD section 2.6)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import ApiError, ERR_VALIDATION


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def now_iso():
    """created_at / updated_at: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Serialize a business datetime; round-trips plain second-precision input."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding (PRD 2.6: round half up; build-budget math stays exact integers)
# ---------------------------------------------------------------------------

def rhu(value):
    """Round a Decimal half-up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num_out(d):
    """Decimal -> JSON number, int when integral."""
    d = Decimal(d)
    return int(d) if d == d.to_integral_value() else float(d)


# ---------------------------------------------------------------------------
# Request body + field validation (pipeline step 4: request shape)
# ---------------------------------------------------------------------------

def json_body():
    """Parse the request body as JSON regardless of Content-Type.

    Empty body -> {} (action endpoints legitimately take no input). A present
    but unparseable body, or a parsed value that is not a JSON object, is a
    request-shape error (pipeline step 4).
    """
    data = request.get_json(force=True, silent=True)
    if data is None:
        if request.data or request.form:
            raise ApiError(ERR_VALIDATION, 400, "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' is required and must be a string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a string")
    return v


def req_int(body, field, min_value=None):
    v = body.get(field)
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' is required and must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be at least {min_value}")
    return v


def opt_int(body, field, default=None, min_value=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an integer")
    if min_value is not None and v < min_value:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be at least {min_value}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_number(body, field):
    """A JSON number (int or float), stored as Decimal. Booleans rejected."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' is required and must be a number")
    try:
        return Decimal(str(v))
    except Exception:
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a number")


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3: limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def pagination_params():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "offset must be non-negative")
    return limit, offset


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------

def new_record(**fields):
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "updated_at": None,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec["updated_at"] = rec["created_at"]
    rec.update(fields)
    return rec


def touch(rec):
    """A direct mutation: refresh updated_at and bump version."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def refresh(rec):
    """A derived-field recompute: value change refreshes updated_at only.

    Per PRD 2.4 the production version is advanced only by its own transitions,
    the BUILT cascade touch, and rental-offer creation; derived recomputes never
    bump version, and the same rule is applied uniformly to every entity.
    """
    rec["updated_at"] = now_iso()


def to_public(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = num_out(v)
        else:
            out[k] = v
    return out
