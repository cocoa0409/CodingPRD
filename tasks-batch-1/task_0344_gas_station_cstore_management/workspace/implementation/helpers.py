"""Shared helpers: auth/role checks, money rounding, pagination, FK existence,
OCC checks, derived recomputation, and field serialization.

Every behavior traces to a PRD sentence; section references appear in comments.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db, now_iso
from errors import (
    fail,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION,
    ERR_STALE_VERSION,
)

ROLES = {"StationManager", "CashierAttendant", "LoyaltyMember"}


# --------------------------------------------------------------------------- #
# Auth (§2.1)
# --------------------------------------------------------------------------- #
def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    §2.1: every request must carry X-User-ID and X-User-Role; if either is
    missing or malformed -> ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not str(user_id).strip() or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers")
    return user_id, role


def require_role(role, allowed):
    """§2.1: role not permitted for the operation -> ERR_FORBIDDEN."""
    if role not in allowed:
        fail(ERR_FORBIDDEN, "Role %s is not permitted for this operation" % role)


# --------------------------------------------------------------------------- #
# Body parsing / field validation (priority 4: ERR_INVALID_REQUEST, §2.8)
# --------------------------------------------------------------------------- #
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            fail(ERR_INVALID_REQUEST, "Missing required field: %s" % n)


def require_string(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        fail(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name, non_negative=True):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if non_negative and v < 0:
        fail(ERR_INVALID_REQUEST, "Field %s must be non-negative" % name)
    return v


def require_number(body, name, non_negative=True):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    if non_negative and v < 0:
        fail(ERR_INVALID_REQUEST, "Field %s must be non-negative" % name)
    return v


def require_enum(body, name, allowed):
    v = body.get(name)
    if v not in allowed:
        fail(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, allowed))
    return v


def optional_int(body, name, non_negative=True):
    if name not in body or body[name] is None:
        return None
    return require_int(body, name, non_negative=non_negative)


# --------------------------------------------------------------------------- #
# Money & gallon precision (§2.7)
# --------------------------------------------------------------------------- #
def round_half_up(value):
    """Round a numeric value to whole cents using round-half-up (§2.7)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to two decimal places, round-half-up (margin_pct, §3.10)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def g3(value):
    """Carry gallon quantities to three decimal places (§2.7)."""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Existence / FK resolution (priority 3: ERR_NOT_FOUND, §2.6)
# --------------------------------------------------------------------------- #
def must_exist(collection, ident):
    rec = collection.get(ident)
    if rec is None:
        fail(ERR_NOT_FOUND, "Referenced resource does not exist")
    return rec


# --------------------------------------------------------------------------- #
# System fields / mutation bookkeeping (§2.4)
# --------------------------------------------------------------------------- #
def _clock_ts(station=None):
    """§2.5: the system runs on the station's business clock, not wall-clock.
    All time-dependent fields (incl. created_at/updated_at, which feed the
    margin window predicate) are stamped from the owning station's current_utc.
    Falls back to wall-clock only for station-less records."""
    if station is not None and station.get("current_utc"):
        return station["current_utc"]
    return now_iso()


def stamp_new(rec, station=None):
    """Initialize common system fields on a freshly created record (§2.4)."""
    ts = _clock_ts(station)
    rec.setdefault("id", None)
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def bump(rec, station=None):
    """A mutation: refresh updated_at and increment version by 1 (§2.4)."""
    rec["updated_at"] = _clock_ts(station)
    rec["version"] = rec.get("version", 1) + 1
    return rec


# --------------------------------------------------------------------------- #
# Optimistic concurrency (§2.10)
# --------------------------------------------------------------------------- #
def check_occ(body, field, current_version):
    """OCC check: provided expected version must equal current version.

    §2.10 / scaffold priority 15: mismatch -> ERR_STALE_VERSION (412).
    These endpoints require the field; it is validated as a non-negative int
    by the route before this call.
    """
    expected = body.get(field)
    if expected != current_version:
        fail(ERR_STALE_VERSION, "%s does not match current version" % field)


# --------------------------------------------------------------------------- #
# Pagination (§2.3, priority 17: ERR_VALIDATION)
# --------------------------------------------------------------------------- #
def parse_pagination():
    """Parse limit/offset query params. §2.3 defaults: limit 10 (1..100),
    offset 0 (>=0). Out of range -> ERR_VALIDATION."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(ERR_VALIDATION, "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            fail(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (tie-break by insertion seq), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# --------------------------------------------------------------------------- #
# Serialization — strip internal fields (e.g. _seq) from output.
# --------------------------------------------------------------------------- #
def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def public_list(recs):
    return [public(r) for r in recs]
