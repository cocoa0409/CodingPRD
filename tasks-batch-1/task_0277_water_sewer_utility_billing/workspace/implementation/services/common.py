"""Shared service helpers: validation, parsing, rounding, pagination, serialization."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.6) — round-half-up to whole cents/gallons.
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value to the nearest whole integer, half up.

    value may be int, float, or Decimal — we route through Decimal so the
    half-up boundary is exact (not IEEE-754 banker's rounding).
    """
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Datetime parsing (ISO 8601 UTC)
# ---------------------------------------------------------------------------
def parse_datetime(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Returns None if value is not a valid datetime string.
    """
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


# ---------------------------------------------------------------------------
# Request body / field validation (PRD §2.8: ERR_INVALID_REQUEST = 422)
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the JSON body as a dict, or {} when absent/empty."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % field)
    return val


def require_int(body, field, minimum=None, maximum=None):
    val = body.get(field)
    # bool is a subclass of int — reject it explicitly.
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s." % (field, maximum))
    return val


def optional_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field, minimum, maximum)


def require_datetime(body, field):
    raw = body.get(field)
    dt = parse_datetime(raw)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be an ISO-8601 datetime." % field)
    return dt


def require_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        if default is not None:
            return default
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % field)
    val = body.get(field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return val


def require_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        if default is not None:
            return default
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % field)
    val = body.get(field)
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % field)
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10 [1,100]; offset default 0 [0,inf).
# Out-of-bounds -> ERR_VALIDATION_LIMIT (422).
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "limit must be within [1,100].")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "offset must be an integer.")
        if offset < 0:
            raise errors.err(errors.ERR_VALIDATION_LIMIT, "offset must be >= 0.")

    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (tie-break internal _seq), then window."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# ---------------------------------------------------------------------------
# Serialization — strip internal keys (those starting with "_").
# ---------------------------------------------------------------------------
def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]
