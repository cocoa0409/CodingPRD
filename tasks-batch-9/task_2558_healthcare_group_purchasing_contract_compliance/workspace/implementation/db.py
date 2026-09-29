"""In-memory data store plus the logical clock (PRD section 2.4).

The store starts empty on every boot: no entity is ever seeded, preloaded or
hardcoded here. Tests construct all state through the declared endpoints.
"""

import re
import uuid
from datetime import datetime, timezone

# Before the clock capability is called for the first time the logical clock
# reads exactly this instant, and it never falls back to wall-clock time.
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(:(\d{2})(\.\d+)?)?"
    r"(Z|z|[+-]\d{2}:\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_timestamp(raw):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    if not _TS_RE.match(raw.strip()):
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(raw):
    """Parse a strict YYYY-MM-DD calendar date. Returns the string or None."""
    if not isinstance(raw, str) or not _DATE_RE.match(raw):
        return None
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return raw


def format_timestamp(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


class Database(object):
    def __init__(self):
        self.contracts = {}
        self.contract_items = {}
        self.members = {}
        self.reviews = {}
        self.commitments = {}
        self.xrefs = {}
        self.activations = {}
        self.files = {}
        self.purchase_lines = {}
        self.measurements = {}
        self.distributions = {}
        # Exact ledger amounts a distributor file posted at load time, so a
        # reversal can compensate by the recorded amounts rather than re-derive.
        self.file_load_deltas = {}
        self._seq = 0
        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock_dt = parse_timestamp(DEFAULT_CLOCK_RAW)

    # -- logical clock ---------------------------------------------------
    def set_clock(self, raw, moment):
        self.clock_raw = raw
        self.clock_dt = moment

    def now_iso(self):
        return format_timestamp(self.clock_dt)

    def today(self):
        """The logical clock's current calendar date as YYYY-MM-DD."""
        moment = self.clock_dt.astimezone(timezone.utc)
        return "%04d-%02d-%02d" % (moment.year, moment.month, moment.day)

    # -- row helpers -----------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, versioned=True):
        stamp = self.now_iso()
        row = {"id": str(uuid.uuid4()), "created_at": stamp}
        if versioned:
            row["updated_at"] = stamp
            row["version"] = 1
        row["_seq"] = self.next_seq()
        return row

    def touch(self, row):
        """Every accepted mutation refreshes updated_at and bumps version."""
        row["updated_at"] = self.now_iso()
        row["version"] = row.get("version", 1) + 1
        return row


db = Database()


def ordered(rows):
    """Default list order: created_at ascending -- oldest first, newest last."""
    return sorted(rows, key=lambda row: row["_seq"])
