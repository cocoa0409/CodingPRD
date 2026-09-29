"""In-memory data store, logical clock and common-field helpers.

The store starts EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

from errors import NOT_FOUND, ApiError
from response import wall_timestamp

KINDS = (
    "taxpayers",
    "information_returns",
    "industry_projects",
    "audit_leads",
    "audits",
    "statute_waivers",
    "sampling_agreements",
    "sample_units",
    "exemption_certificates",
    "use_tax_purchases",
    "assessments",
    "assessment_adjustments",
    "appeal_proceedings",
    "payment_arrangements",
)

S = {kind: {} for kind in KINDS}

_SEQ = itertools.count(1)

# ---------------------------------------------------------------- logical clock
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = {"now": DEFAULT_CLOCK}


def clock_now():
    return _CLOCK["now"]


def clock_date():
    return _CLOCK["now"].date()


def set_clock(instant):
    _CLOCK["now"] = instant


def clock_instant_str():
    return format_instant(_CLOCK["now"])


# --------------------------------------------------------------- date / instant
def format_instant(dt):
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


def parse_date(value):
    """Parse a bare calendar date. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    head = text
    if "T" in head:
        head = head.split("T", 1)[0]
    elif " " in head:
        head = head.split(" ", 1)[0]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        d = parse_date(value)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    """Whole calendar days from start to end (may be negative)."""
    return (end - start).days


def add_days(d, n):
    return d + timedelta(days=n)


# --------------------------------------------------------------- record helpers
def new_record(fields, common=True):
    rec = {"id": str(uuid.uuid4())}
    rec.update(fields)
    rec["created_at"] = wall_timestamp()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next(_SEQ)
    rec["_common"] = common
    return rec


def insert(kind, rec):
    S[kind][rec["id"]] = rec
    return rec


def touch(rec):
    if rec.get("_common"):
        rec["updated_at"] = wall_timestamp()
        rec["version"] = rec.get("version", 1) + 1
    return rec


def get(kind, rid):
    if not isinstance(rid, str):
        return None
    return S[kind].get(rid)


def must_get(kind, rid):
    rec = get(kind, rid)
    if rec is None:
        raise ApiError(NOT_FOUND[kind])
    return rec


def all_of(kind):
    """Every record of a family, in default sort order (created_at ASC)."""
    return sorted(S[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(kind, **eq):
    out = []
    for rec in all_of(kind):
        if all(rec.get(k) == v for k, v in eq.items()):
            out.append(rec)
    return out


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def reset():
    for kind in KINDS:
        S[kind].clear()
    _CLOCK["now"] = DEFAULT_CLOCK
