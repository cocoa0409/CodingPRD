"""In-memory data store, logical clock, and record helpers.

The store starts EMPTY on every boot. Nothing is seeded here.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

LOCK = threading.RLock()

# ---------------------------------------------------------------- logical clock
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}

# ---------------------------------------------------------------- stores
elections = {}
voters = {}
reviewers = {}
ballot_requests = {}
address_verifications = {}
enrollments = {}
mailing_batches = {}
ballot_packets = {}
return_envelopes = {}
signature_reviews = {}
cure_notices = {}
cure_evidence = {}
remake_records = {}
observer_sessions = {}
transparency_log = {}

_seq_counter = {"n": 0}


def reset():
    for store in (
        elections, voters, reviewers, ballot_requests, address_verifications,
        enrollments, mailing_batches, ballot_packets, return_envelopes,
        signature_reviews, cure_notices, cure_evidence, remake_records,
        observer_sessions, transparency_log,
    ):
        store.clear()
    _clock["now"] = CLOCK_DEFAULT
    _seq_counter["n"] = 0


def now():
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------- datetimes
def iso(dt):
    """Canonical emission form: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(raw):
    """Lenient ISO 8601 parse; returns None when unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(raw):
    """Strict YYYY-MM-DD parse; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def add_days(dt, days):
    """Day arithmetic adds exact 24-hour multiples (PRD 2.8)."""
    return dt + timedelta(days=days)


def whole_second(dt):
    return dt.replace(microsecond=0)


# ---------------------------------------------------------------- records
def make_record(store, fields, common=True):
    rec = {"id": new_id()}
    rec.update(fields)
    stamp = now()
    rec["created_at"] = stamp
    if common:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version -- every mutation, cascades included."""
    if rec is None:
        return rec
    rec["updated_at"] = now()
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    return rec


def ordered(values):
    """Default collection ordering: created_at ASC (stable by insertion)."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
