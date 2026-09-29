"""In-memory data store, logical clock and shared constants.

Storage is process-local Python dicts keyed by id.  Nothing is seeded: every
entity is created through the declared API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- constants
SECONDS_PER_DAY = 86400
MAX_TOLL_SECONDS = 864000          # 10 whole days of authorization-defect tolling
MILLICENTS_PER_CENT = 1000
GRACE_BUSINESS_DAYS = 2
MAX_DELIVERY_ATTEMPTS = 3
REVIEW_WINDOW_DAYS = 30
AMENDMENT_WINDOW_DAYS = 60

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

CATEGORIES = [
    "GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "SUD_PART2", "HIV", "GENETIC",
    "REPRODUCTIVE_HEALTH", "MINOR_CONFIDENTIAL", "PSYCHOTHERAPY_NOTES",
]
PROTECTED_CATEGORIES = [
    "BEHAVIORAL_HEALTH", "SUD_PART2", "HIV", "GENETIC",
    "REPRODUCTIVE_HEALTH", "MINOR_CONFIDENTIAL", "PSYCHOTHERAPY_NOTES",
]
SOURCE_SYSTEMS = ["EHR_CURRENT", "LEGACY_ARCHIVE", "IMAGING_PACS", "SCANNED_PAPER"]
REQUESTER_TYPES = [
    "PATIENT", "PERSONAL_REPRESENTATIVE", "ATTORNEY", "INSURER", "EMPLOYER",
    "RESEARCHER", "GOVERNMENT_AGENCY", "OTHER_PROVIDER",
]
DELIVERY_FORMATS = [
    "PAPER_MAIL", "CD_ROM", "SECURE_PORTAL", "DIRECT_MESSAGE",
    "UNENCRYPTED_EMAIL", "FAX",
]
ELECTRONIC_FORMATS = ["SECURE_PORTAL", "DIRECT_MESSAGE", "UNENCRYPTED_EMAIL"]
ACCESS_BASES = ["PATIENT_RIGHT_OF_ACCESS", "THIRD_PARTY_AUTHORIZATION"]
FULFILLMENT_STATES = [
    "INTAKE_REVIEW", "AUTH_DEFECT_PENDING", "COMPILATION", "SENSITIVE_REVIEW",
    "REDACTION", "RELEASE_READY", "RELEASED", "DENIED", "CLOSED", "CANCELLED",
]
TERMINAL_FULFILLMENT = ["CLOSED", "CANCELLED"]
BILLING_STATES = ["PENDING_INVOICE", "INVOICED", "PAID", "WAIVED", "NOT_BILLABLE"]
EVENT_TYPES = [
    "STATUTORY_DEADLINE_BREACHED", "PENALTY_ACCRUED", "DENIAL_ISSUED",
    "DENIAL_OVERTURNED", "AUTHORIZATION_REVOKED", "AUTHORIZATION_EXPIRED",
    "SENSITIVE_WITHHOLD", "AMENDMENT_NOTICE_REQUIRED", "FEE_CAP_APPLIED",
    "DELIVERY_FAILED",
]
DENIAL_GROUNDS = [
    "NO_VALID_AUTHORIZATION", "PSYCHOTHERAPY_NOTES_EXCLUDED",
    "RECORD_NOT_MAINTAINED", "HARM_REVIEW_LICENSED_PROFESSIONAL",
    "INMATE_SAFETY", "RESEARCH_IN_PROGRESS",
]
REVIEWABLE_GROUNDS = ["HARM_REVIEW_LICENSED_PROFESSIONAL", "INMATE_SAFETY"]

# ---------------------------------------------------------------- clock
_clock = {"now": DEFAULT_CLOCK}
_counter = itertools.count(1)


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    return next(_counter)


def new_id():
    return str(uuid.uuid4())


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 UTC instant.  Returns None when not a valid UTC instant."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    tz = m.group(8)
    if tz is not None and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        try:
            offs = sign * (int(body[:2]) * 60 + int(body[2:]))
        except ValueError:
            return None
        if offs != 0:
            return None
    try:
        frac = m.group(7) or ".0"
        micro = int(round(float(frac) * 1000000))
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        return None


def add_days(dt, days):
    return dt + timedelta(seconds=int(days) * SECONDS_PER_DAY)


# ---------------------------------------------------------------- collections
state_fee_rules = {}
facilities = {}
patients = {}
requesters = {}
authorizations = {}
requests = {}
segments = {}
invoices = {}
invoice_lines = {}
deliveries = {}
denials = {}
amendments = {}
compliance_events = {}

ALL_COLLECTIONS = [
    state_fee_rules, facilities, patients, requesters, authorizations, requests,
    segments, invoices, invoice_lines, deliveries, denials, amendments,
    compliance_events,
]


def common_fields(full=True):
    """Common properties (PRD 2.4).  Lean records carry only id and created_at."""
    stamp = fmt(now())
    rec = {"id": new_id(), "created_at": stamp}
    if full:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1."""
    rec["updated_at"] = fmt(now())
    rec["version"] = rec.get("version", 1) + 1


def public(rec):
    """Strip internal bookkeeping keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(records):
    """Default list ordering: created_at ascending, then append order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
