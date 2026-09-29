"""Shared foundation: constants, in-memory store, envelope, errors, helpers.

Storage is process-memory only.  Nothing is ever written to disk and nothing is
seeded at import time: a fresh boot exposes empty collections.
"""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

# --------------------------------------------------------------------------
# §1.6 Global constants (pinned)
# --------------------------------------------------------------------------
APPEAL_WINDOW_DAYS = 14
PRE_REVIEW_FRESHNESS_HOURS = 72
MIN_SCREENSHOTS_PER_CLASS = 2
CREDENTIAL_EXPIRY_WARNING_HOURS = 168
PROVISIONAL_CONFIDENCE_FLOOR = Decimal("0.8000")
DISCLOSURE_PASS_THRESHOLD = Decimal("0.9500")
POSTURE_INDEX_FLOOR = Decimal("90.00")
ACCEPT_NO_CHANGE_SEVERITY_CEILING = Decimal("6.00")
EXPEDITE_STANDING_FLOOR = Decimal("60.00")
EXPEDITE_CREDITS_PER_WINDOW = 2
BASE_SLA_HOURS = 48
PHASE_COUNT = 7
MIN_PHASE_DWELL_HOURS = 24
ROLLBACK_COOLDOWN_HOURS = 72
POOL_MAX_CONCURRENT_SLOTS = 10
ROLLING_WINDOW_DAYS = 365
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

PHASE_PCTS = [Decimal("1"), Decimal("2"), Decimal("5"), Decimal("10"),
              Decimal("20"), Decimal("50"), Decimal("100")]
RATING_BANDS = [0, 4, 9, 12, 17, 18]

ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
         "PlatformReviewer", "PlatformAppealBoard", "PlatformPolicyAdmin",
         "Auditor"]
ACCOUNT_BACKED_ROLES = {"PublisherAdmin", "ReleaseManager", "ComplianceOfficer"}

# --------------------------------------------------------------------------
# §5 Error identifiers -> HTTP status
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CROSS_ACCOUNT_ACCESS_DENIED": 403,
    "ERR_PROGRAM_MEMBERSHIP_EXPIRED": 403,
    "ERR_ACCOUNT_SUSPENDED": 403,
    "ERR_PUBLISHER_ACCOUNT_NOT_FOUND": 404,
    "ERR_SIGNING_CREDENTIAL_NOT_FOUND": 404,
    "ERR_APP_RECORD_NOT_FOUND": 404,
    "ERR_GUIDELINE_RULE_NOT_FOUND": 404,
    "ERR_FEATURE_MAPPING_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_METADATA_LOCALE_NOT_FOUND": 404,
    "ERR_BEHAVIOR_FINDING_NOT_FOUND": 404,
    "ERR_REJECTION_REASON_NOT_FOUND": 404,
    "ERR_APPEAL_REQUEST_NOT_FOUND": 404,
    "ERR_EXPEDITE_REQUEST_NOT_FOUND": 404,
    "ERR_REVIEW_CAPACITY_WINDOW_NOT_FOUND": 404,
    "ERR_ROLLOUT_PLAN_NOT_FOUND": 404,
    "ERR_COMMERCE_ITEM_NOT_FOUND": 404,
    "ERR_IMPACT_ASSESSMENT_NOT_FOUND": 404,
    "ERR_VALIDATION": 422,
    "ERR_STALE_APP_RECORD_VERSION": 412,
    "ERR_STALE_PUBLISHER_ACCOUNT_VERSION": 412,
    "ERR_INVALID_SUBMISSION_STATE": 409,
    "ERR_INVALID_LISTING_STATE": 409,
    "ERR_INVALID_DISTRIBUTION_STATE": 409,
    "ERR_INVALID_CREDENTIAL_STATE": 409,
    "ERR_INVALID_ROLLOUT_STATE": 409,
    "ERR_INVALID_GUIDELINE_STATE": 409,
    "ERR_INVALID_MAPPING_STATE": 409,
    "ERR_INVALID_IMPACT_STATE": 409,
    "ERR_INVALID_APPEAL_STATE": 409,
    "ERR_INVALID_EXPEDITE_STATE": 409,
    "ERR_INVALID_COMMERCE_ITEM_STATE": 409,
    "ERR_INVALID_FINDING_STATE": 409,
    "ERR_REVIEW_WINDOW_CLOSED": 409,
    "ERR_APP_COMPLIANCE_FROZEN": 409,
    "ERR_APP_COMPLIANCE_RESTRICTED": 409,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 409,
    "ERR_CRITICAL_FINDING_UNRESOLVED": 409,
    "ERR_PRIVACY_DISCLOSURE_INACCURATE": 409,
    "ERR_AGE_RATING_UNDERSTATED": 409,
    "ERR_TRACKING_CONSENT_PROMPT_MISSING": 409,
    "ERR_DISCLOSURE_STILL_MISSING": 409,
    "ERR_SIGNING_CREDENTIAL_INVALID": 409,
    "ERR_CREDENTIAL_PLATFORM_MISMATCH": 409,
    "ERR_CREDENTIAL_NOT_YET_VALID": 409,
    "ERR_LINKED_CERT_NOT_ACTIVE": 409,
    "ERR_KEY_CUSTODY_NOT_PERMITTED": 409,
    "ERR_CREDENTIAL_IN_USE": 409,
    "ERR_CREDENTIAL_EXPIRES_BEFORE_DEADLINE": 409,
    "ERR_GUIDELINE_MAPPING_INCOMPLETE": 409,
    "ERR_GUIDELINE_RULE_NOT_EFFECTIVE": 409,
    "ERR_RULE_NOT_YET_EFFECTIVE": 409,
    "ERR_REMEDIATION_INCOMPLETE": 409,
    "ERR_METADATA_INCOMPLETE": 409,
    "ERR_DUPLICATE_PRIMARY_LOCALE": 409,
    "ERR_SCREENSHOT_SET_INCOMPLETE": 409,
    "ERR_REJECTION_RESPONSE_REQUIRED": 409,
    "ERR_REJECTION_NOT_CONTESTED": 409,
    "ERR_PRE_REVIEW_NOT_PASSED": 409,
    "ERR_PRE_REVIEW_STALE": 409,
    "ERR_DUPLICATE_BUILD_NUMBER": 409,
    "ERR_REVIEW_POOL_OVERSUBSCRIBED": 409,
    "ERR_ROLLOUT_WINDOW_CONFLICT": 409,
    "ERR_ROLLOUT_MODE_MISMATCH": 409,
    "ERR_PHASE_SEQUENCE_INVALID": 409,
    "ERR_APP_NOT_DISTRIBUTED": 409,
    "ERR_WAIVER_NOT_PERMITTED": 409,
    "ERR_EVIDENCE_REQUIRED": 409,
    "ERR_IMPACT_TOO_SEVERE": 409,
    "ERR_EXTERNAL_LINK_NOT_PERMITTED": 409,
    "ERR_APPEAL_WINDOW_EXPIRED": 409,
    "ERR_APPEAL_ALREADY_OPEN": 409,
    "ERR_PHASE_DWELL_NOT_MET": 409,
    "ERR_ROLLOUT_NOT_DUE": 409,
    "ERR_NO_REVIEW_CAPACITY": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 409,
    "ERR_EXPEDITE_QUOTA_EXHAUSTED": 409,
    "ERR_STANDING_TOO_LOW": 409,
    "ERR_REVENUE_ALREADY_REPORTED": 409,
}

NOT_FOUND_CODE = {
    "publisher_account": "ERR_PUBLISHER_ACCOUNT_NOT_FOUND",
    "signing_credential": "ERR_SIGNING_CREDENTIAL_NOT_FOUND",
    "app_record": "ERR_APP_RECORD_NOT_FOUND",
    "guideline_rule": "ERR_GUIDELINE_RULE_NOT_FOUND",
    "feature_mapping": "ERR_FEATURE_MAPPING_NOT_FOUND",
    "submission": "ERR_SUBMISSION_NOT_FOUND",
    "metadata_locale": "ERR_METADATA_LOCALE_NOT_FOUND",
    "behavior_finding": "ERR_BEHAVIOR_FINDING_NOT_FOUND",
    "rejection_reason": "ERR_REJECTION_REASON_NOT_FOUND",
    "appeal_request": "ERR_APPEAL_REQUEST_NOT_FOUND",
    "expedite_request": "ERR_EXPEDITE_REQUEST_NOT_FOUND",
    "review_capacity_window": "ERR_REVIEW_CAPACITY_WINDOW_NOT_FOUND",
    "rollout_plan": "ERR_ROLLOUT_PLAN_NOT_FOUND",
    "commerce_item": "ERR_COMMERCE_ITEM_NOT_FOUND",
    "impact_assessment": "ERR_IMPACT_ASSESSMENT_NOT_FOUND",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# In-memory store.  Every collection is a plain dict keyed by row id.
# --------------------------------------------------------------------------
COLLECTIONS = [
    "publisher_account", "signing_credential", "app_record", "guideline_rule",
    "feature_mapping", "submission", "metadata_locale", "behavior_finding",
    "rejection_reason", "appeal_request", "expedite_request",
    "review_capacity_window", "rollout_plan", "commerce_item",
    "impact_assessment",
]

DB = {name: {} for name in COLLECTIONS}
CLOCK = {"current_utc": DEFAULT_CLOCK}
_SEQ = {"n": 0}


def table(kind):
    return DB[kind]


def rows(kind):
    """All rows of a collection ordered by created_at then insertion order."""
    return sorted(DB[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))


def get_row(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[kind].get(row_id)


# --------------------------------------------------------------------------
# Logical clock / time helpers
# --------------------------------------------------------------------------
ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$")


def parse_iso(value):
    """Parse a strict ISO 8601 UTC instant, or return None."""
    if not isinstance(value, str) or not ISO_RE.match(value):
        return None
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def fmt_iso_ms(dt):
    """Render with three fractional digits (created_at / updated_at / meta)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_iso(dt):
    """Render a domain instant, omitting a fractional part that is exactly zero."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_iso_ms(dt)


def now_dt():
    return parse_iso(CLOCK["current_utc"])


def now_iso():
    return fmt_iso(now_dt())


def now_iso_ms():
    return fmt_iso_ms(now_dt())


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# Decimal helpers
# --------------------------------------------------------------------------
def d2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def d4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def num2(value):
    """Render a 2-decimal number for JSON as a float-like Decimal."""
    return float(d2(value))


def num4(value):
    return float(d4(value))


def cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Row creation / mutation bookkeeping
# --------------------------------------------------------------------------
def new_row(kind, fields):
    _SEQ["n"] += 1
    stamp = now_iso_ms()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_kind": kind,
        "_seq": _SEQ["n"],
    }
    row.update(fields)
    DB[kind][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and advance version by exactly 1."""
    if row is None:
        return None
    row["updated_at"] = now_iso_ms()
    row["version"] = row["version"] + 1
    return row


# --------------------------------------------------------------------------
# Response envelope (§2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso_ms()}


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public(row):
    """Row as the API exposes it: internal bookkeeping keys stripped."""
    if row is None:
        return None
    return {k: jsonable(v) for k, v in row.items() if not k.startswith("_")}


def ok(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _base_meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    })
    body = {"meta": meta, "response_type": "array", "data": [jsonable(i) for i in items]}
    return jsonify(body), 200


def error_response(error_id, message):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_STATUS.get(error_id, 400)


# --------------------------------------------------------------------------
# Pagination + list plumbing (§2.3)
# --------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit, offset = 10, 0
    if limit_raw is not None:
        if not re.fullmatch(r"-?\d+", limit_raw.strip()):
            fail("ERR_VALIDATION", "limit must be an integer")
        limit = int(limit_raw)
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset_raw is not None:
        if not re.fullmatch(r"-?\d+", offset_raw.strip()):
            fail("ERR_VALIDATION", "offset must be an integer")
        offset = int(offset_raw)
        if offset < 0:
            fail("ERR_VALIDATION", "offset may not be negative")
    return limit, offset


def paginate(items):
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([public(r) for r in page], limit, offset, total)


def arg_filter(name, enum=None):
    """Read an exact-match query filter; unknown enum members simply match nothing."""
    value = request.args.get(name)
    if value is None:
        return None
    return value


def arg_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not re.fullmatch(r"-?\d+", value.strip()):
        fail("ERR_VALIDATION", "%s must be an integer" % name)
    return int(value)


def arg_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be a boolean" % name)


# --------------------------------------------------------------------------
# Request context, header shape (rung 10) and role permission (rung 15)
# --------------------------------------------------------------------------
def endpoint(roles, name=None):
    """Decorator applying the first two rungs of the rejection ladder."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            account_id = request.headers.get("X-Publisher-Account-Id")
            if role is None or role not in ROLES:
                fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                     "X-User-Role is missing or not a recognised role")
            if user_id is None or user_id.strip() == "":
                fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                     "X-User-ID is missing or empty")
            if role in ACCOUNT_BACKED_ROLES:
                if account_id is None or account_id.strip() == "":
                    fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                         "X-Publisher-Account-Id is required for %s" % role)
            else:
                account_id = None
            if role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED",
                     "role %s may not call this endpoint" % role)
            g.role = role
            g.user_id = user_id
            g.account_id = account_id
            g.scoped = role in ACCOUNT_BACKED_ROLES
            return fn(*args, **kwargs)
        wrapper.__name__ = name or fn.__name__
        return wrapper
    return decorator


# --------------------------------------------------------------------------
# Tenancy chains (§2.1) and reference resolution (rungs 20 + 25)
# --------------------------------------------------------------------------
def owner_account_id(row):
    """The PublisherAccount id a row resolves to, or None for platform rows."""
    if row is None:
        return None
    kind = row.get("_kind")
    if kind == "publisher_account":
        return row["id"]
    if kind in ("signing_credential", "app_record", "expedite_request"):
        return row.get("publisher_account_id")
    if kind in ("feature_mapping", "submission", "rollout_plan",
                "commerce_item", "impact_assessment"):
        return owner_account_id(get_row("app_record", row.get("app_record_id")))
    if kind in ("metadata_locale", "behavior_finding", "rejection_reason",
                "appeal_request"):
        return owner_account_id(get_row("submission", row.get("submission_id")))
    return None


def resolve(specs):
    """Two-pass reference resolution.

    ``specs`` is an ordered list of ``(kind, value)`` or ``(kind, value, code)``
    tuples: path identifiers first, then body fields in declaration order.
    Tenancy (403) is checked for every resolvable reference before any
    existence failure (404) is reported, per §2.1.
    """
    found = []
    for spec in specs:
        kind, value = spec[0], spec[1]
        row = get_row(kind, value)
        found.append(row)
        if row is not None and g.get("scoped"):
            owner = owner_account_id(row)
            if owner is not None and owner != g.account_id:
                fail("ERR_CROSS_ACCOUNT_ACCESS_DENIED",
                     "resource belongs to another publisher account")
    out = []
    for spec, row in zip(specs, found):
        kind, value = spec[0], spec[1]
        code = spec[2] if len(spec) > 2 else NOT_FOUND_CODE[kind]
        if row is None:
            if value is None or not isinstance(value, str):
                out.append(None)
                continue
            fail(code, "%s %r does not exist" % (kind, value))
        out.append(row)
    return out


def scope_rows(items):
    """Narrow a list result to the caller's account for account-backed roles."""
    if not g.get("scoped"):
        return items
    return [r for r in items if owner_account_id(r) == g.account_id]


def body_json():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return data
