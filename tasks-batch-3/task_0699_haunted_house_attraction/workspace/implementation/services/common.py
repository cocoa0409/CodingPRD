"""Shared service helpers: input validation, timestamp bumps, serialization,
and the round-half-up money helper.
"""
from decimal import Decimal, ROUND_HALF_UP

import db
import errors
from errors import ApiError


# ---------------------------------------------------------------------------
# Money / rounding (PRD §2.7)
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Input validation helpers. A malformed body, missing required field, or
# invalid enum value -> ERR_INVALID_REQUEST (400) (PRD §2.6).
# ---------------------------------------------------------------------------
def _bad(msg):
    raise ApiError(errors.ERR_INVALID_REQUEST, 400, msg)


def require_str(body, key):
    val = body.get(key)
    if not isinstance(val, str) or val.strip() == "":
        _bad(f"Field '{key}' is required and must be a non-empty string.")
    return val


def require_int(body, key, minimum=None, maximum=None):
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(f"Field '{key}' is required and must be an integer.")
    if minimum is not None and val < minimum:
        _bad(f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        _bad(f"Field '{key}' must be <= {maximum}.")
    return val


def optional_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body.get(key) is None:
        return default
    return require_int(body, key, minimum=minimum, maximum=maximum)


def require_number(body, key, minimum=None, maximum=None):
    val = body.get(key)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad(f"Field '{key}' is required and must be a number.")
    if minimum is not None and val < minimum:
        _bad(f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        _bad(f"Field '{key}' must be <= {maximum}.")
    return val


def optional_number(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body.get(key) is None:
        return default
    return require_number(body, key, minimum=minimum, maximum=maximum)


def require_bool(body, key, default=None):
    if key not in body or body.get(key) is None:
        if default is None:
            _bad(f"Field '{key}' is required and must be a boolean.")
        return default
    val = body.get(key)
    if not isinstance(val, bool):
        _bad(f"Field '{key}' must be a boolean.")
    return val


def require_enum(body, key, allowed):
    val = body.get(key)
    if not isinstance(val, str) or val not in allowed:
        _bad(f"Field '{key}' must be one of {sorted(allowed)}.")
    return val


def require_datetime(body, key):
    val = body.get(key)
    if not isinstance(val, str):
        _bad(f"Field '{key}' is required and must be an ISO 8601 datetime string.")
    dt = db.parse_iso(val)
    if dt is None:
        _bad(f"Field '{key}' must be a valid ISO 8601 datetime.")
    return dt


# ---------------------------------------------------------------------------
# System field helpers (PRD §2.4)
# created_at / updated_at are recorded from real wall-clock time as ISO 8601
# UTC with three fractional digits — audit timestamps distinct from the logical
# business clock used for entry/shift/waiver rules.
# ---------------------------------------------------------------------------
def audit_now():
    from datetime import datetime, timezone
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_record(with_version=True):
    """Common system fields for a freshly created entity (PRD §2.4).

    `with_version=False` for immutable entities (PricingRule, PassProduct) which
    carry only id + created_at.
    """
    ts = audit_now()
    rec = {
        "id": _new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def _new_id():
    import db
    return db.new_id()


def touch(record):
    """Refresh updated_at and bump version by one (a mutation, PRD §2.4)."""
    record["updated_at"] = audit_now()
    record["version"] = record.get("version", 1) + 1


# ---------------------------------------------------------------------------
# List helpers (PRD §2.3): sort by created_at ascending, then paginate. Records
# created in the same millisecond keep insertion order via a stable secondary
# key (the monotonic creation sequence).
# ---------------------------------------------------------------------------
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def sort_and_paginate(records, limit, offset):
    """Sort records by (created_at asc, creation sequence asc), then page."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
