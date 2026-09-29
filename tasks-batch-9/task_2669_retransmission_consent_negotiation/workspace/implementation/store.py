"""In-memory data store, logical clock and shared primitives.

The store is EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Tests build every entity through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timedelta, timezone

# --- Section 2.5: the logical clock and the statutory calendar --------------
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
ELECTION_DEADLINE_UTC = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
AUDIT_RIGHTS_WINDOW_DAYS = 180
MIN_GOOD_FAITH_MEETINGS = 3
MAX_RATE_PER_SUB_CENTS = 600
MAX_ESCALATOR_BP = 1000
MAX_CUMULATIVE_EXTENSION_DAYS = 90
MAX_SPLIT_BP = 6000
PENETRATION_GRACE_BP = 50
PENALTY_MULTIPLIER = 2
AMU_DISCOUNT_BP = 8800
RIGHTS_CREDIT_BP = {"DIGITAL": 800, "OUT_OF_HOME": 500, "STREAMING": 1200}
RIGHTS_TERM_ORDER = ["DIGITAL", "OUT_OF_HOME", "STREAMING"]

ROLES = [
    "CarriageAdmin",
    "StationGroupNegotiator",
    "GroupCounsel",
    "DistributorRep",
    "NetworkRepresentative",
    "ComplianceOfficer",
]

ALL_ROLES = list(ROLES)
# Distributor subscriber data is not the network's business (PRD 2.10).
NO_NETWORK_ROLES = [
    "CarriageAdmin",
    "StationGroupNegotiator",
    "GroupCounsel",
    "DistributorRep",
    "ComplianceOfficer",
]
# The station group's reverse-compensation split is not the distributor's
# business (PRD 2.10).
NO_DISTRIBUTOR_ROLES = [
    "CarriageAdmin",
    "StationGroupNegotiator",
    "GroupCounsel",
    "NetworkRepresentative",
    "ComplianceOfficer",
]

lock = threading.RLock()


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self.seq = 0
        self.stations = {}
        self.affiliations = {}
        self.distributors = {}
        self.elections = {}
        self.negotiations = {}
        self.offers = {}
        self.good_faith = {}
        self.reports = {}
        self.findings = {}
        self.agreements = {}
        self.extensions = {}
        self.disputes = {}
        self.notices = {}
        self.settlements = {}


db = DB()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq


def clock():
    return db.clock


def fmt_dt_millis(dt):
    """Render with three fractional digits, always.

    PRD 2.2 requires this of `api_request_timestamp` and PRD 2.4 requires it of
    `created_at`; those are the only two fields the PRD pins to this precision.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_dt(dt):
    """Render a domain `*_utc` instant, preserving the precision it actually has.

    The PRD never asks a business instant to carry fractional digits. It pins the
    logical clock to exactly `2026-08-01T00:00:00Z` (PRD 2.5), and says an
    agreement "carries the supplied `effective_start_utc`" (PRD 3.7), so a
    second-precision instant must round-trip as second-precision rather than
    being rewritten into the `created_at` house format. Sub-second inputs still
    render their milliseconds so no supplied precision is lost.
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_dt_millis(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def now_iso():
    """Domain timestamps read the logical clock, never wall-clock time."""
    return fmt_dt(db.clock)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def sort_rows(rows):
    """Creation-timestamp ascending, with insertion order as the tie-break."""
    return sorted(rows, key=lambda r: r["_seq"])


def base_row(with_version=True):
    row = {"id": new_id(), "_seq": next_seq(), "created_at": fmt_dt_millis(db.clock)}
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """A mutation: refresh updated_at and advance version (PRD 2.4)."""
    row["updated_at"] = fmt_dt_millis(db.clock)
    row["version"] = int(row.get("version", 1)) + 1
