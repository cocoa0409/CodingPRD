"""Core infrastructure: in-memory store, logical clock, response envelope,
error catalogue, auth/RBAC and payload validation helpers."""

import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# ---------------------------------------------------------------- logical clock

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """Purely in-memory store.  Starts completely empty on every boot: no
    seeding, no preloading, no persistence of any kind."""

    def __init__(self):
        self.state_law_profiles = {}
        self.union_minimum_schedules = {}
        self.talents = {}
        self.estate_authorities = {}
        self.consent_grants = {}
        self.biometric_assets = {}
        self.digital_replicas = {}
        self.generated_performances = {}
        self.usage_licenses = {}
        self.compensation_entries = {}
        self.infringement_cases = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
LOCK = threading.RLock()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------- time utilities

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:[Zz]|[+-]\d{2}:?\d{2})?)?$"
)


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _DT_RE.match(text):
        return None
    text = text.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_ms(value):
    """ISO 8601 UTC timestamp with exactly three fractional digits.

    Used for ``created_at``, ``updated_at`` and ``api_request_timestamp``, the
    three stamps the PRD declares as carrying three fractional digits.
    """
    if value is None:
        return None
    v = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond // 1000,
    )


def iso(value):
    """ISO 8601 UTC instant at whole-second resolution.

    Every other instant in the system -- logical-clock stamps and the whole-day
    deadlines derived from them -- is written the way the PRD writes it, e.g.
    ``2027-08-16T00:00:00Z``.  A sub-second instant (only reachable when a caller
    drives the clock to one) keeps three fractional digits so nothing is lost.
    """
    if value is None:
        return None
    v = value.astimezone(timezone.utc)
    if v.microsecond:
        return iso_ms(v)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        v.year, v.month, v.day, v.hour, v.minute, v.second,
    )


MILLISECOND_FIELDS = ("created_at", "updated_at")


def add_days(base, days):
    return base + timedelta(days=int(days))


def add_years(base, years):
    """Advance to the same month and day in the later year; 29 February
    collapses to 28 February in a non-leap year."""
    year = base.year + int(years)
    month = base.month
    day = base.day
    if month == 2 and day == 29:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        if not leap:
            day = 28
    return base.replace(year=year, month=month, day=day)


def at_midnight(value):
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def whole_months(start, end):
    """Number of complete calendar months between two instants."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return months


# ------------------------------------------------------------------ money maths

def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-int(places))
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_up(value, places=0):
    quantum = Decimal(1).scaleb(-int(places))
    return Decimal(value).quantize(quantum, rounding=ROUND_CEILING)


def dec(value):
    return Decimal(str(value))


# -------------------------------------------------------------- error catalogue

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TALENT_NOT_FOUND": 404,
    "ERR_ESTATE_AUTHORITY_NOT_FOUND": 404,
    "ERR_CONSENT_GRANT_NOT_FOUND": 404,
    "ERR_BIOMETRIC_ASSET_NOT_FOUND": 404,
    "ERR_DIGITAL_REPLICA_NOT_FOUND": 404,
    "ERR_GENERATED_PERFORMANCE_NOT_FOUND": 404,
    "ERR_USAGE_LICENSE_NOT_FOUND": 404,
    "ERR_INFRINGEMENT_CASE_NOT_FOUND": 404,
    "ERR_COMPENSATION_ENTRY_NOT_FOUND": 404,
    "ERR_STATE_LAW_PROFILE_MISSING": 422,
    "ERR_UNION_SCHEDULE_MISSING": 422,
    "ERR_NOT_TALENT_REPRESENTATIVE": 403,
    "ERR_NOT_ESTATE_REPRESENTATIVE": 403,
    "ERR_NOT_LICENSEE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_TALENT_VERSION_STALE": 412,
    "ERR_REPLICA_VERSION_STALE": 412,
    "ERR_INVALID_TALENT_STATE": 409,
    "ERR_INVALID_ESTATE_AUTHORITY_STATE": 409,
    "ERR_INVALID_CONSENT_STATE": 409,
    "ERR_CONSENT_NOT_ACTIVE": 409,
    "ERR_INVALID_ASSET_STATE": 409,
    "ERR_INVALID_REPLICA_STATE": 409,
    "ERR_INVALID_PERFORMANCE_STATE": 409,
    "ERR_INVALID_LICENSE_STATE": 409,
    "ERR_INVALID_DISCLOSURE_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_TALENT_RIGHTS_FROZEN": 409,
    "ERR_TALENT_RIGHTS_RESTRICTED": 409,
    "ERR_ESTATE_AUTHORITY_UNVERIFIED": 409,
    "ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD": 409,
    "ERR_ASSET_UNDER_LEGAL_HOLD": 409,
    "ERR_ASSET_BOUND_TO_ACTIVE_REPLICA": 409,
    "ERR_POSTMORTEM_REGISTRATION_MISSING": 422,
    "ERR_POSTMORTEM_RIGHTS_EXPIRED": 422,
    "ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT": 422,
    "ERR_DISCLOSURE_NOT_VERIFIED": 409,
    "ERR_TAKEDOWN_MANDATORY": 409,
    "ERR_MEDIA_TYPE_OUT_OF_SCOPE": 422,
    "ERR_TERRITORY_OUT_OF_SCOPE": 422,
    "ERR_ASSET_CONSENT_MISMATCH": 422,
    "ERR_NO_SOURCE_ASSETS": 422,
    "ERR_CONSENT_TERM_INVALID": 422,
    "ERR_WINDOW_EXCEEDS_CONSENT_TERM": 422,
    "ERR_OUTSIDE_DISTRIBUTION_WINDOW": 409,
    "ERR_EXCLUSIVITY_WINDOW_CONFLICT": 409,
    "ERR_REPLICA_OVERLAP_CAP_EXCEEDED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_CONSENT_NOT_REVOCABLE": 409,
    "ERR_SEVERITY_BELOW_ESCALATION_FLOOR": 409,
    "ERR_COMPENSATION_BELOW_STATUTORY_FLOOR": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ------------------------------------------------------------ response envelope

def _meta():
    token = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))
    stamp = datetime.now(timezone.utc)
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": iso_ms(stamp),
    }


def public(row):
    """Serialise a stored row: drop private keys, render datetimes."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_ms(value) if key in MILLISECOND_FIELDS else iso(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out


def respond(data, status=200, pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ------------------------------------------------------------------ auth / RBAC

ROLES = (
    "RightsAdministrator",
    "ComplianceOfficer",
    "TalentRepresentative",
    "EstateRepresentative",
    "LicenseeProducer",
)
ALL_ROLES = ROLES


def authorize(*allowed):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header must name a declared role")
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "role %s may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


# -------------------------------------------------------- version bump tracking

def touch(row):
    """Record that the current request mutated a versioned row.  The row's
    version advances by exactly one per request no matter how many hops of a
    cascade touch it, and the bump is visible immediately so the response body
    carries the new counter."""
    if row is None or "version" not in row:
        return
    tracked = getattr(g, "_touched", None)
    if tracked is None:
        tracked = set()
        g._touched = tracked
    if row["id"] in tracked:
        row["updated_at"] = now()
        return
    tracked.add(row["id"])
    row["version"] = int(row["version"]) + 1
    row["updated_at"] = now()


# ------------------------------------------------------- payload / query helpers

_MISSING = object()


def body_json():
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        invalid("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        invalid("request body must be a JSON object")
    return parsed


def _present(body, key):
    return key in body and body[key] is not None


def want_str(body, key, min_len=1, max_len=None, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        invalid("%s must be a string" % key)
    if min_len is not None and min_len >= 1 and not value.strip():
        invalid("%s must not be blank" % key)
    if min_len is not None and len(value) < min_len:
        invalid("%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        invalid("%s must be at most %d characters" % (key, max_len))
    return value


def want_enum(body, key, allowed, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        invalid("%s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def want_int(body, key, minimum=None, maximum=None, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool):
        invalid("%s must be an integer" % key)
    if isinstance(value, str):
        invalid("%s must be a JSON number, not a string" % key)
    if isinstance(value, float):
        if not float(value).is_integer():
            invalid("%s must be a whole number" % key)
        value = int(value)
    if not isinstance(value, int):
        invalid("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        invalid("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be at most %d" % (key, maximum))
    return int(value)


def want_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        invalid("%s must be a boolean" % key)
    return value


def want_dt(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    parsed = parse_dt(body[key])
    if parsed is None:
        invalid("%s must be a parseable ISO 8601 datetime" % key)
    return parsed


def want_pct(body, key, minimum, maximum, min_exclusive, max_exclusive,
             decimals=4, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool) or isinstance(value, str):
        invalid("%s must be a JSON number" % key)
    if not isinstance(value, (int, float)):
        invalid("%s must be a JSON number" % key)
    amount = dec(value)
    lo = dec(minimum)
    hi = dec(maximum)
    if amount < lo or (min_exclusive and amount == lo):
        invalid("%s is out of range" % key)
    if amount > hi or (max_exclusive and amount == hi):
        invalid("%s is out of range" % key)
    if -amount.as_tuple().exponent > decimals:
        invalid("%s must carry at most %d decimals" % (key, decimals))
    return amount


CODE_RE = re.compile(r"^[A-Z]{2}$")


def want_code(body, key, required=True, default=None):
    value = want_str(body, key, 1, None, required, None)
    if value is None:
        return default
    if not CODE_RE.match(value):
        invalid("%s must be exactly two uppercase letters" % key)
    return value


def want_code_list(body, key, max_items, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, list):
        invalid("%s must be an array" % key)
    if len(value) < 1:
        invalid("%s must not be empty" % key)
    if len(value) > max_items:
        invalid("%s may hold at most %d members" % (key, max_items))
    for item in value:
        if not isinstance(item, str) or not CODE_RE.match(item):
            invalid("%s members must be two uppercase letters" % key)
    if len(set(value)) != len(value):
        invalid("%s members must be distinct" % key)
    return list(value)


def want_enum_list(body, key, allowed, max_items, required=True, default=None):
    if not _present(body, key):
        if required:
            invalid("%s is required" % key)
        return default
    value = body[key]
    if not isinstance(value, list):
        invalid("%s must be an array" % key)
    if len(value) < 1:
        invalid("%s must not be empty" % key)
    if len(value) > max_items:
        invalid("%s may hold at most %d members" % (key, max_items))
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("%s members must be drawn from %s" % (key, ", ".join(sorted(allowed))))
    if len(set(value)) != len(value):
        invalid("%s members must be distinct" % key)
    return list(value)


def want_id_list(body, key, max_items):
    """Array of identifiers.  Emptiness and duplication are deliberately NOT
    rejected here -- they belong to the referential rung."""
    if key not in body or body[key] is None:
        invalid("%s is required" % key)
    value = body[key]
    if not isinstance(value, list):
        invalid("%s must be an array" % key)
    if len(value) > max_items:
        invalid("%s may hold at most %d members" % (key, max_items))
    for item in value:
        if not isinstance(item, str) or not item.strip():
            invalid("%s members must be identifier strings" % key)
    return list(value)


# --------------------------------------------------------------------- paging

def paging():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if str(raw).strip() != str(limit):
            invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid("limit must lie within 1 through 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if str(raw).strip() != str(offset):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset may not be negative")
    return limit, offset


def page_out(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return [public(r) for r in window], pagination


def apply_filters(rows, spec):
    """spec maps query-parameter name -> row field name."""
    args = request.args
    out = rows
    for param, field in spec.items():
        if param in args and args.get(param) != "":
            wanted = args.get(param)
            out = [r for r in out if str(r.get(field)) == wanted]
    return out


def by_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def collection(rows, filters, order="created_asc"):
    limit, offset = paging()
    rows = apply_filters(list(rows), filters)
    if order == "created_desc_id":
        rows = sorted(rows, key=lambda r: r["id"])
        rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    elif order == "effective_from_asc":
        rows = sorted(rows, key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))
    elif order == "posted_at_asc":
        rows = sorted(rows, key=lambda r: (r["posted_at"], r["created_at"], r["_seq"]))
    else:
        rows = by_created_asc(rows)
    data, pagination = page_out(rows, limit, offset)
    return respond(data, 200, pagination)
