"""In-memory data store, id minting and the server's logical clock.

The store starts completely empty on every boot: no seeding, no preloaded rows.
Every row is created by callers through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone

# PRD section 2.5: the logical clock starts at exactly this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_instant(value):
    """Parse an ISO-8601 instant into a naive UTC datetime; None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def parse_day(value):
    """Parse a strict YYYY-MM-DD calendar date; None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_instant(moment):
    """ISO-8601 UTC with exactly three fractional digits (PRD section 2.4)."""
    if moment is None:
        return None
    return "%s.%03dZ" % (moment.strftime("%Y-%m-%dT%H:%M:%S"), moment.microsecond // 1000)


def fmt_like(moment, sample):
    """Render `moment` in the same fractional style as the `sample` input string."""
    if moment is None:
        return None
    if isinstance(sample, str) and "." in sample:
        return fmt_instant(moment)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_day(day):
    if day is None:
        return None
    return day.strftime("%Y-%m-%d")


class Store(object):
    """Every collection is a plain dict keyed by the server-minted id."""

    def __init__(self):
        self.assessors = {}
        self.asv_vendors = {}
        self.engagements = {}
        self.network_segments = {}
        self.system_components = {}
        self.sampling_plans = {}
        self.requirement_assessments = {}
        self.evidence_items = {}
        self.ccws = {}
        self.remediation_items = {}
        self.rocs = {}
        self.scan_cycles = {}
        self.scan_findings = {}
        self.change_log_entries = {}
        self._seq = 0
        self.clock = parse_instant(DEFAULT_CLOCK_ISO)
        self.clock_sample = DEFAULT_CLOCK_ISO

    # ---- identity / ordering -------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock -------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_instant(self.clock)

    def today(self):
        return self.clock.date()

    def current_utc(self):
        return fmt_like(self.clock, self.clock_sample)

    def set_clock(self, moment, sample):
        self.clock = moment
        self.clock_sample = sample

    # ---- row helpers ---------------------------------------------------------
    def stamp_new(self, row, versioned=True):
        """Attach the common system fields to a brand new row."""
        row["id"] = self.new_id()
        row["_seq"] = self.next_seq()
        row["created_at"] = self.now_iso()
        if versioned:
            row["updated_at"] = self.now_iso()
            row["version"] = 1
        # A row's version starts at 1 on creation, so a cascade later in the same
        # request must not push a brand new row to 2.
        _already_bumped(row)
        return row

    def touch(self, row):
        """Advance a row's concurrency field and modification stamp.

        A single request advances a given row's `version` by exactly 1 no matter
        how many links of a cascade write to it (PRD section 2.4), so the bump is
        recorded once per request and later touches only refresh `updated_at`.
        """
        if row is None:
            return None
        already = _already_bumped(row)
        if "version" in row and not already:
            row["version"] = row["version"] + 1
        if "updated_at" in row:
            row["updated_at"] = self.now_iso()
        return row


def _already_bumped(row):
    """True when this request has already advanced this row's version once."""
    row_id = row.get("id")
    if row_id is None:
        return False
    try:
        from flask import g, has_request_context
    except ImportError:  # pragma: no cover - flask is a hard dependency
        return False
    if not has_request_context():
        return False
    bumped = getattr(g, "_bumped_rows", None)
    if bumped is None:
        bumped = set()
        g._bumped_rows = bumped
    if row_id in bumped:
        return True
    bumped.add(row_id)
    return False


def ordered(rows):
    """Default list order: created_at ascending, insertion sequence as tie break."""
    return sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("_seq") or 0))


def add_days(moment, days):
    return moment + timedelta(days=days)


# The single process-wide store. A fresh process means a fresh, empty store.
db = Store()
