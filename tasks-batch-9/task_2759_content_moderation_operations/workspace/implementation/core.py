"""Core infrastructure: logical clock, in-memory store, response envelope,
errors, authentication/authorization and request well-formedness helpers.

Every structural name in this module is taken verbatim from PRD.md §2 and
SCAFFOLD.yaml (response_envelope / validations / errors).
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# Error catalogue (PRD §5 / SCAFFOLD errors)
# --------------------------------------------------------------------------

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_CONTENT_NOT_FOUND": 404,
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_POLICY_VERSION_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_QUEUE_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_DETECTION_SIGNAL_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_AUDIT_SAMPLE_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_NOT_CASE_OWNER": 403,
    "ERR_NOT_APPEAL_REVIEWER": 403,
    "ERR_APPEAL_NOT_OWNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ACCOUNT_BANNED": 403,
    "ERR_CASE_ALREADY_DECIDED": 409,
    "ERR_CASE_NOT_ASSIGNED": 409,
    "ERR_INVALID_CASE_TRANSITION": 409,
    "ERR_POLICY_VERSION_NOT_DRAFT": 409,
    "ERR_POLICY_VERSION_NOT_BACKTESTED": 409,
    "ERR_POLICY_VERSION_NOT_CERTIFIABLE": 409,
    "ERR_CASE_NOT_DECIDED": 409,
    "ERR_APPEAL_NOT_UNDER_REVIEW": 409,
    "ERR_AUDIT_NOT_AUDITABLE": 409,
    "ERR_AUDIT_NOT_DISPUTABLE": 409,
    "ERR_REPORT_NOT_COMPUTED": 409,
    "ERR_REPORT_ALREADY_PUBLISHED": 409,
    "ERR_REVIEWER_NOT_ACTIVE": 409,
    "ERR_REVIEWER_NOT_ON_BREAK": 409,
    "ERR_CONTENT_NOT_LIVE": 409,
    "ERR_NO_ACTIVE_POLICY_VERSION": 409,
    "ERR_REVIEWER_NOT_CERTIFIED": 422,
    "ERR_REVIEWER_LANGUAGE_MISMATCH": 422,
    "ERR_EXPOSURE_CAP_EXCEEDED": 422,
    "ERR_REVIEWER_OFF_SHIFT": 422,
    "ERR_REVIEWER_AT_CAPACITY": 422,
    "ERR_REVIEWER_NOT_ELIGIBLE_FOR_ESCALATION": 422,
    "ERR_NO_ELIGIBLE_REVIEWER": 409,
    "ERR_NO_ELIGIBLE_QUEUE": 422,
    "ERR_APPEAL_ALREADY_EXISTS": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_APPEAL_CREDITS_EXHAUSTED": 402,
    "ERR_WELLNESS_BREAK_OVERLAP": 409,
    "ERR_REPORT_PERIOD_INVALID": 422,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_REPORT_NOT_RESTATED": 422,
    "ERR_OPEN_APPEALS_IN_PERIOD": 422,
    "ERR_BACKTEST_DIVERGENCE_EXCEEDED": 422,
    "ERR_THRESHOLD_ORDER_INVALID": 422,
    "ERR_CHILD_SEVERITY_EXCEEDS_PARENT": 422,
    "ERR_QUEUE_SPECIALTY_MISMATCH": 422,
    "ERR_DUPLICATE_CATEGORY_CODE": 409,
    "ERR_DUPLICATE_HANDLE": 409,
    "ERR_LEGAL_CASE_REQUIRES_JURISDICTION": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_STALE_REVIEWER_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Global constants (SCAFFOLD global_constants)
# --------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
TIER_CONFIDENCE_MULTIPLIER = {
    "STANDARD": Decimal("1.00"),
    "HIGH_PROFILE": Decimal("0.85"),
    "GOVERNMENT": Decimal("0.80"),
}
REPEAT_BONUS_PER_POINT = Decimal("0.01")
REPEAT_BONUS_CAP_POINTS = 10
SEVERITY_POINTS = {"T1": 8, "T2": 4, "T3": 2, "T4": 1}
ACTION_WEIGHT = {
    "REMOVE": Decimal("1.0"),
    "AGE_GATE": Decimal("0.75"),
    "WARN": Decimal("0.25"),
    "NO_ACTION": Decimal("0.0"),
}
REPEAT_MULTIPLIER_STEP = Decimal("0.25")
REPEAT_MULTIPLIER_CAP_REMOVALS = 4
STANDING_LIMITED_AT = 3
STANDING_SUSPENDED_AT = 6
STANDING_BANNED_AT = 10
SEVERITY_SLA_DIVISOR = {"T1": 4, "T2": 2, "T3": 1, "T4": 1}
ESCALATION_SLA_MINUTES = 30
LEGAL_SLA_MINUTES = 1440
MEDIA_EXPOSURE_MULTIPLIER = {"TEXT": 1, "IMAGE": 2, "VIDEO": 3}
RETRAIN_FLOOR = Decimal("0.8500")
SUSPEND_FLOOR = Decimal("0.6000")
MIN_GATE_SAMPLE = 2
MAX_BACKTEST_DIVERGENCE = Decimal("0.2500")
DEFAULT_APPEAL_CREDITS = 3

ROLES = [
    "TrustSafetyAdmin",
    "PolicyManager",
    "Reviewer",
    "QAAuditor",
    "LegalCounsel",
    "AccountHolder",
]

LANGUAGES = ["EN", "ES", "DE", "AR", "HI"]
MEDIA_KINDS = ["TEXT", "IMAGE", "VIDEO"]
SPECIALTIES = ["VIOLENCE", "CSAM_ADJACENT", "HATE", "SPAM", "MISINFO", "SELF_HARM"]
SEVERITY_TIERS = ["T1", "T2", "T3", "T4"]
ACCOUNT_TIERS = ["STANDARD", "HIGH_PROFILE", "GOVERNMENT"]
STANDINGS = ["GOOD_STANDING", "LIMITED", "SUSPENDED", "BANNED"]
VISIBILITY_STATUSES = ["LIVE", "AGE_GATED", "REMOVED", "REINSTATED"]
REVIEW_STATUSES = ["CLEAR", "UNDER_REVIEW", "ACTIONED", "APPEALED"]
CATEGORY_STATUSES = ["DRAFT", "ACTIVE"]
POLICY_VERSION_STATUSES = ["DRAFT", "BACKTESTING", "ACTIVE", "SUPERSEDED"]
ENFORCEMENT_ACTIONS = ["REMOVE", "AGE_GATE", "WARN"]
OUTCOMES = ["REMOVE", "AGE_GATE", "WARN", "NO_ACTION"]
ROLE_CLASSES = ["FRONTLINE", "SENIOR", "QA"]
REVIEWER_STATUSES = ["ACTIVE", "ON_WELLNESS_BREAK", "PENDING_RETRAINING", "SUSPENDED"]
DISPOSITIONS = ["DISCARDED", "AUTO_ACTION", "HUMAN_REVIEW"]
CASE_STATUSES = ["PENDING_ASSIGNMENT", "ASSIGNED", "ESCALATED", "DECIDED"]
CASE_ORIGINS = ["CLASSIFIER", "LEGAL_REQUEST", "MANUAL_REPORT"]
ESCALATION_REASONS = ["IMMINENT_HARM", "LEGAL_REQUEST", "HIGH_PROFILE", "CALIBRATION"]
APPEAL_STATUSES = ["SUBMITTED", "INDEPENDENT_REVIEW", "UPHELD", "OVERTURNED"]
APPEAL_TERMINAL = ["UPHELD", "OVERTURNED"]
APPEAL_OPEN = ["SUBMITTED", "INDEPENDENT_REVIEW"]
RESOLUTIONS = ["UPHELD", "OVERTURNED"]
SAMPLING_REASONS = ["RANDOM", "TARGETED_LOW_ACCURACY", "POST_POLICY_CHANGE"]
VERDICTS = ["AGREE", "DISAGREE_MINOR", "DISAGREE_MATERIAL"]
AUDIT_STATUSES = ["SAMPLED", "AUDITED", "DISPUTED"]
REPORT_STATUSES = ["DRAFT", "COMPUTED", "PUBLISHED"]
REPORT_VARIANTS = ["PROVISIONAL", "RESTATED"]

OPEN_CASE_STATUSES = ["PENDING_ASSIGNMENT", "ASSIGNED", "ESCALATED"]


# --------------------------------------------------------------------------
# Timestamps and the logical clock (PRD §2.4, §2.5)
# --------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant into a naive UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tzs = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tzs and tzs not in ("Z", "z"):
        sign = 1 if tzs[0] == "+" else -1
        body = tzs[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def fmt_ts(dt):
    """Render a naive UTC datetime as ISO 8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class Clock:
    def __init__(self):
        self.current = parse_iso(DEFAULT_CLOCK_UTC)

    def now(self):
        return self.current

    def now_iso(self):
        return fmt_ts(self.current)

    def set(self, dt):
        self.current = dt


# --------------------------------------------------------------------------
# Numeric helpers (PRD §2.6)
# --------------------------------------------------------------------------

Q4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    return Decimal(str(value))


def round4(value):
    """Round half up to four decimal places; returns a Decimal."""
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def num4(value):
    """Four-decimal value rendered as a JSON number."""
    if value is None:
        return None
    return float(round4(value))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def div4(numerator, denominator):
    """round_half_up(numerator / denominator, 4) as a Decimal."""
    return round4(dec(numerator) / dec(denominator))


# --------------------------------------------------------------------------
# In-memory store -- starts completely empty on every boot.  Nothing is ever
# seeded, preloaded or hardcoded here; tests build all state through the API.
# --------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.clock = Clock()
        self.accounts = {}
        self.content_items = {}
        self.policy_categories = {}
        self.policy_versions = {}
        self.reviewers = {}
        self.review_queues = {}
        self.detection_signals = {}
        self.moderation_cases = {}
        self.appeals = {}
        self.audit_samples = {}
        self.transparency_reports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock.now()


def now_iso():
    return db.clock.now_iso()


def base_fields(record):
    """Attach the four system-managed common fields (PRD §2.5)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["updated_at"] = now_iso()
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Any mutation -- including a server-initiated cascade -- refreshes
    updated_at and advances version (PRD §2.5)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


# --------------------------------------------------------------------------
# Response envelope (PRD §2.2, SCAFFOLD response_envelope)
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Authentication and authorization (PRD §2.1, §2.8 tiers 1-2)
# --------------------------------------------------------------------------

class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def reviewer(self):
        return db.reviewers.get(self.user_id)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return Actor(user_id, role)


def require(*allowed_roles):
    actor = authenticate()
    if actor.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % actor.role)
    g.actor = actor
    return actor


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

def paginate_args():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not re.fullmatch(r"-?\d+", (raw or "").strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if not re.fullmatch(r"-?\d+", (raw or "").strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def sort_key(record):
    return (record.get("created_at") or "", record.get("_seq") or 0)


def listing(records, limit, offset, serializer):
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def enum_filter(name, allowed):
    """Read an optional enum-valued query filter, validating its member."""
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a recognised value for %s." % (value, name))
    return value


def str_filter(name):
    if name not in request.args:
        return None
    return request.args.get(name)


# --------------------------------------------------------------------------
# Request well-formedness (PRD §2.8 tier 3 -> ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, minlen=1, maxlen=None):
    if not present(payload, name):
        _bad(name, "is required.")
    value = payload[name]
    if not isinstance(value, str):
        _bad(name, "must be a string.")
    if len(value) < minlen:
        _bad(name, "must be at least %d characters." % minlen)
    if maxlen is not None and len(value) > maxlen:
        _bad(name, "must be at most %d characters." % maxlen)
    return value


def opt_str(payload, name, minlen=0, maxlen=None, default=None):
    if not present(payload, name):
        return default
    return req_str(payload, name, minlen, maxlen)


def req_int(payload, name, lo=None, hi=None):
    if not present(payload, name):
        _bad(name, "is required.")
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer.")
    if lo is not None and value < lo:
        _bad(name, "must be at least %s." % lo)
    if hi is not None and value > hi:
        _bad(name, "must be at most %s." % hi)
    return value


def opt_int(payload, name, lo=None, hi=None, default=None):
    if not present(payload, name):
        return default
    return req_int(payload, name, lo, hi)


def req_num(payload, name, lo=None, hi=None):
    if not present(payload, name):
        _bad(name, "is required.")
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number.")
    d = dec(value)
    if lo is not None and d < dec(lo):
        _bad(name, "must be at least %s." % lo)
    if hi is not None and d > dec(hi):
        _bad(name, "must be at most %s." % hi)
    return d


def opt_num(payload, name, lo=None, hi=None, default=None):
    if not present(payload, name):
        return default
    return req_num(payload, name, lo, hi)


def req_bool(payload, name):
    if not present(payload, name):
        _bad(name, "is required.")
    value = payload[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean.")
    return value


def opt_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    return req_bool(payload, name)


def req_enum(payload, name, allowed):
    value = req_str(payload, name, 1, None)
    if value not in allowed:
        _bad(name, "is not a recognised enum member.")
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_enum_array(payload, name, allowed):
    if not present(payload, name):
        _bad(name, "is required.")
    value = payload[name]
    if not isinstance(value, list) or not value:
        _bad(name, "must be a non-empty array.")
    seen = set()
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            _bad(name, "contains an unrecognised member.")
        if member in seen:
            _bad(name, "must not contain duplicates.")
        seen.add(member)
    return list(value)


def opt_id_array(payload, name):
    if not present(payload, name):
        return []
    value = payload[name]
    if not isinstance(value, list):
        _bad(name, "must be an array.")
    for member in value:
        if not isinstance(member, str) or not member:
            _bad(name, "must contain only non-empty strings.")
    return list(value)


def req_ts(payload, name):
    raw = req_str(payload, name, 1, None)
    parsed = parse_iso(raw)
    if parsed is None:
        _bad(name, "must be an ISO 8601 instant.")
    return parsed


UPPER2 = re.compile(r"^[A-Z]{2}$")
CATEGORY_CODE = re.compile(r"^[A-Z][A-Z_]{2,39}$")
