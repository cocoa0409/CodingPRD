"""In-memory data store and the logical clock (PRD §2.4, §2.5).

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Every record any caller needs is created through the declared
API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.4 — the logical clock's startup value.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_DEFAULT
        self._counter = itertools.count(1)
        self.service_plans = {}
        self.fee_line_items = {}
        self.methodology_documents = {}
        self.measurement_probes = {}
        self.test_runs = {}
        self.attestations = {}
        self.label_versions = {}
        self.label_translations = {}
        self.subscriber_accounts = {}
        self.label_disclosures = {}
        self.complaints = {}
        self.remediation_credits = {}
        self.regulator_inquiries = {}
        self.plan_change_notices = {}

    def next_seq(self):
        return next(self._counter)


store = Store()


# ---------------------------------------------------------------------------
# clock / timestamp helpers
# ---------------------------------------------------------------------------

def now():
    """The logical clock as an aware datetime."""
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def now_iso():
    return iso(now())


def parse_iso(value):
    """Parse an ISO 8601 instant, returning an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _ISO_RE.match(text):
        return None
    text = text.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def dt_of(record, field):
    """Parse a stored datetime string field (None-safe)."""
    if record is None:
        return None
    return parse_iso(record.get(field))


def plus_days(dt, days):
    return dt + timedelta(days=days)


def whole_days_between(start, end):
    """floor((end - start) / 86400 seconds)."""
    import math
    return int(math.floor((end - start).total_seconds() / 86400.0))


def elapsed_30day_months(start, end):
    """floor((end - start) / 2_592_000 seconds) — PHASE_MONTH_SECONDS."""
    import math
    return int(math.floor((end - start).total_seconds() / 2592000.0))


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------

def new_record(common_fields=True):
    """A fresh record carrying the common identity fields (PRD §2.5)."""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Record a mutation: refresh updated_at and bump version (PRD §2.5)."""
    if record is None:
        return
    record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] = record["version"] + 1


def ordered(values):
    """Rows in ascending creation order (created_at ASC, insertion tie-break)."""
    return sorted(values, key=lambda r: r["_seq"])
