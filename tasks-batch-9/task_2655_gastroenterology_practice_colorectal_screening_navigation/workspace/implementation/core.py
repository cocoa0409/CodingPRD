"""Core primitives: logical clock, in-memory store, error catalogue, response envelope."""
import calendar
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLES = (
    "PracticeAdmin",
    "ReferralCoordinator",
    "PatientNavigator",
    "Endoscopist",
    "Pathologist",
    "BillingSpecialist",
    "QualityOfficer",
    "Patient",
)

# --------------------------------------------------------------------------
# Error catalogue (PRD section 5)
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_CLINICIAN_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_COVERAGE_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_EPISODE_NOT_FOUND": 404,
    "ERR_TEST_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_PATHOLOGY_NOT_FOUND": 404,
    "ERR_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_QUALITY_PERIOD_NOT_FOUND": 404,
    "ERR_INVALID_REFERRAL_STATE": 409,
    "ERR_INVALID_EPISODE_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_SESSION_NOT_ACCEPTING_BOOKINGS": 409,
    "ERR_INVALID_BOOKING_STATE": 409,
    "ERR_INVALID_PATHOLOGY_STATE": 409,
    "ERR_INVALID_CLAIM_STATE": 409,
    "ERR_INVALID_QUALITY_PERIOD_STATE": 409,
    "ERR_TEST_ALREADY_RESULTED": 409,
    "ERR_STALE_SESSION_VERSION": 412,
    "ERR_STALE_EPISODE_VERSION": 412,
    "ERR_OPEN_ACCESS_RISK_SCREEN_FAILED": 422,
    "ERR_CLINICIAN_CREDENTIAL_SUSPENDED": 422,
    "ERR_PREPROCEDURE_RISK_UNCLEARED": 422,
    "ERR_PREP_NOT_CONFIRMED": 422,
    "ERR_ANESTHESIA_COVERAGE_REQUIRED": 409,
    "ERR_CLINICIAN_TYPE_MISMATCH": 422,
    "ERR_REFERRAL_NOT_ACCEPTED": 422,
    "ERR_EPISODE_NOT_ELIGIBLE": 422,
    "ERR_PATHOLOGY_NOT_FINALIZED": 409,
    "ERR_SLOT_OUTSIDE_SESSION_WINDOW": 422,
    "ERR_SLOT_OVERLAP": 409,
    "ERR_ANESTHESIA_CONCURRENCY_EXCEEDED": 409,
    "ERR_COVERAGE_WINDOW_INSUFFICIENT": 422,
    "ERR_QUALITY_PERIOD_NOT_ENDED": 422,
    "ERR_QUALITY_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_DUPLICATE_OPEN_EPISODE": 409,
    "ERR_NO_SPECIMENS": 422,
    "ERR_OVERRIDE_OUT_OF_RANGE": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_SESSION_CAPACITY_EXCEEDED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# In-memory store.  Starts completely empty on every boot - nothing is seeded.
# --------------------------------------------------------------------------
LOGICAL_CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.plans = {}
        self.patients = {}
        self.clinicians = {}
        self.sessions = {}
        self.coverages = {}
        self.referrals = {}
        self.episodes = {}
        self.tests = {}
        self.bookings = {}
        self.reports = {}
        self.recommendations = {}
        self.claims = {}
        self.periods = {}
        self.clock = LOGICAL_CLOCK_EPOCH
        self.seq = 0


db = Store()


# --------------------------------------------------------------------------
# Clock / timestamps
# --------------------------------------------------------------------------
def now():
    return db.clock


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


def today():
    return db.clock.astimezone(timezone.utc).date()


def today_str():
    return today().isoformat()


def parse_instant(text):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(text, str) or "T" not in text:
        return None
    raw = text.strip()
    body = raw
    tz = timezone.utc
    if body.endswith("Z") or body.endswith("z"):
        body = body[:-1]
    elif "+" in body[10:]:
        base, off = body.rsplit("+", 1)
        if off not in ("00:00", "0000", "00"):
            return None
        body = base
    elif body[10:].count("-") >= 1:
        idx = body.rfind("-")
        if idx > 10:
            off = body[idx + 1:]
            if off not in ("00:00", "0000", "00"):
                return None
            body = body[:idx]
    try:
        parsed = datetime.fromisoformat(body)
    except Exception:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc)
    return parsed.replace(tzinfo=tz)


def parse_date(text):
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def add_days(d, days):
    return d + timedelta(days=days)


def add_months(d, months):
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# --------------------------------------------------------------------------
# Rounding helpers
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def money(value):
    return int(round_half_up(value, 0))


def num2(value):
    return float(round_half_up(value, 2))


def num4(value):
    return float(round_half_up(value, 4))


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------
def new_record(fields):
    db.seq += 1
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = now_iso()
    rec["updated_at"] = now_iso()
    rec["version"] = 1
    rec["_seq"] = db.seq
    return rec


def touch(rec):
    rec["version"] = int(rec.get("version", 1)) + 1
    rec["updated_at"] = now_iso()


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }


def respond_object(rec, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(rec) if rec else {}}
    return jsonify(body), status


def respond_empty(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def respond_list(rows, pagination, status=200):
    meta = _meta()
    meta.update(pagination)
    body = {"meta": meta, "response_type": "array", "data": [public(r) for r in rows]}
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
