"""Core helpers: in-memory store, logical clock, response envelope, auth,
validation primitives, date/decimal utilities, error catalogue.

Every structural name (headers, envelope fields, pagination fields, error ids)
is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""

import calendar
import secrets
import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5) — error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_LANDLORD_NOT_FOUND": 404,
    "ERR_LEASEHOLDER_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_SETTLEMENT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_FEE_NOT_FOUND": 404,
    "ERR_LEASE_NOT_VERIFIABLE": 409,
    "ERR_LEASE_NOT_PENDING_REVIEW": 409,
    "ERR_LEASE_NOT_VERIFIED": 409,
    "ERR_LEASE_DATES_INVALID": 422,
    "ERR_LISTING_TYPE_NOT_ALLOWED": 409,
    "ERR_LISTING_NOT_DRAFT": 409,
    "ERR_LISTING_NOT_PENDING_APPROVAL": 409,
    "ERR_LISTING_NOT_OPEN": 409,
    "ERR_LISTING_NOT_WITHDRAWABLE": 409,
    "ERR_INVALID_DATE_RANGE": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_OUTSIDE_AVAILABILITY_WINDOW": 422,
    "ERR_TERM_TOO_SHORT": 409,
    "ERR_APPLICATION_NOT_SCREENABLE": 409,
    "ERR_APPLICATION_NOT_IN_SCREENING": 409,
    "ERR_APPLICATION_NOT_INFO_REQUESTED": 409,
    "ERR_APPLICATION_NOT_SCREENED": 409,
    "ERR_APPLICATION_NOT_MATCHED": 409,
    "ERR_SCREENING_NOT_PASSED": 409,
    "ERR_APPLICATION_NOT_ACTIONABLE": 409,
    "ERR_STALE_LISTING_VERSION": 412,
    "ERR_OCCUPANCY_OVERLAP": 409,
    "ERR_AGREEMENT_NOT_DRAFT": 409,
    "ERR_AGREEMENT_NOT_PENDING_SIGNATURES": 409,
    "ERR_INVALID_SIGNER_ROLE": 409,
    "ERR_DUPLICATE_SIGNATURE": 409,
    "ERR_AGREEMENT_NOT_EXECUTED": 409,
    "ERR_SETTLEMENT_NOT_FUNDED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_VOIDABLE": 409,
    "ERR_SETTLEMENT_NOT_PENDING": 409,
    "ERR_FUNDING_AMOUNT_MISMATCH": 402,
    "ERR_SETTLEMENT_NOT_HANDED_OFF": 409,
    "ERR_AGREEMENT_NOT_READY_FOR_HANDOFF": 409,
    "ERR_APPOINTMENT_CONFLICT": 409,
    "ERR_APPOINTMENT_NOT_SCHEDULED": 409,
    "ERR_DISPUTE_NOT_FILED": 409,
    "ERR_DISPUTE_NOT_UNDER_REVIEW": 409,
    "ERR_INVALID_DISPUTE_OUTCOME": 422,
    "ERR_FEE_NOT_PENDING": 409,
    "ERR_FEE_NOT_CHARGED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5) — startup default 2026-05-01T00:00:00Z, never wall-clock
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def now_iso():
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    dt = _CLOCK["now"].astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# In-memory store (empty at boot — no seeding)
# ---------------------------------------------------------------------------
STORE = {
    "landlords": {},
    "leaseholders": {},
    "applicants": {},
    "leases": {},
    "listings": {},
    "applications": {},
    "screening_reports": {},
    "agreements": {},
    "signatures": {},
    "settlements": {},
    "appointments": {},
    "disputes": {},
    "fees": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def gen_id():
    return str(uuid.uuid4())


def new_common(with_common=True):
    """Return a base dict with id + (optionally) created_at/updated_at/version."""
    ts = now_iso()
    base = {"id": gen_id(), "created_at": ts, "_seq": next_seq()}
    if with_common:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    """Mutation: refresh updated_at and bump version (PRD §2.4/§2.10)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_array(items, limit, offset, total_count, code=200):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(extra), "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(error_id, message=None):
    status = ERROR_STATUS.get(error_id, 400)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
VALID_ROLES = {"Landlord", "Leaseholder", "Applicant", "ComplianceOfficer", "PlatformAdmin"}


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or uid.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------------------
# Existence lookups
# ---------------------------------------------------------------------------
def get_or_404(kind, ident, error_id):
    ent = STORE[kind].get(ident)
    if ent is None:
        raise ApiError(error_id)
    return ent


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def get_body():
    if request.data is None or request.data == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Body must be a JSON object")
    return data


_MISSING = object()


def req_str(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise ApiError("ERR_VALIDATION", "Missing field: %s" % key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Invalid string: %s" % key)
    return v


def opt_str(body, key, default=""):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", "Invalid string: %s" % key)
    return v


def req_int(body, key, min_val=None, max_val=None):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise ApiError("ERR_VALIDATION", "Missing field: %s" % key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Invalid integer: %s" % key)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", "Below minimum: %s" % key)
    if max_val is not None and v > max_val:
        raise ApiError("ERR_VALIDATION", "Above maximum: %s" % key)
    return v


def opt_int(body, key, default, min_val=None, max_val=None):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Invalid integer: %s" % key)
    if min_val is not None and v < min_val:
        raise ApiError("ERR_VALIDATION", "Below minimum: %s" % key)
    if max_val is not None and v > max_val:
        raise ApiError("ERR_VALIDATION", "Above maximum: %s" % key)
    return v


def opt_bool(body, key, default=False):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Invalid boolean: %s" % key)
    return v


def req_enum(body, key, choices, error_id="ERR_VALIDATION"):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        raise ApiError("ERR_VALIDATION", "Missing field: %s" % key)
    if v not in choices:
        raise ApiError(error_id, "Invalid value for %s" % key)
    return v


def opt_enum(body, key, choices, default):
    v = body.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if v not in choices:
        raise ApiError("ERR_VALIDATION", "Invalid value for %s" % key)
    return v


# ---------------------------------------------------------------------------
# Date / datetime parsing (all comparisons via logical clock semantics)
# ---------------------------------------------------------------------------
def parse_date(body, key):
    v = req_str(body, key)
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Invalid date: %s" % key)


def parse_datetime_field(body, key):
    v = req_str(body, key)
    return parse_iso_datetime(v)


def parse_iso_datetime(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "Invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit out of bounds")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "Invalid offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset out of bounds")
    return limit, offset


def paginate(rows):
    """rows: list of entity dicts. Sort by created_at asc (tiebreak insertion)."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serialize(e) for e in page], limit, offset, total


# ---------------------------------------------------------------------------
# Decimal / money helpers (PRD §2.7)
# ---------------------------------------------------------------------------
def round_half_up_int(numerator, denominator):
    """round_half_up(numerator/denominator) -> int cents."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_rate(rate_str, amount):
    """round_half_up(rate * amount) -> int cents (rate given as decimal string)."""
    q = (Decimal(rate_str) * Decimal(amount)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round4(value):
    """round_half_up to 4 dp, returned as float for JSON."""
    q = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------
def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]


def days_remaining_inclusive(d):
    """days_in_month(D) - day_of_month(D) + 1  (inclusive of move-in day)."""
    return days_in_month(d) - d.day + 1


def months_between(move_in, move_out_inclusive):
    """Whole calendar months of occupancy for the inclusive interval
    [move_in, move_out]. The exclusive end is move_out + 1 day."""
    end_excl = move_out_inclusive + timedelta(days=1)
    months = (end_excl.year - move_in.year) * 12 + (end_excl.month - move_in.month)
    if end_excl.day < move_in.day:
        months -= 1
    return months
