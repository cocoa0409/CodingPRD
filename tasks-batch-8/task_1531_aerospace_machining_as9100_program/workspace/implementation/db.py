"""In-memory data store and logical clock.

Storage is dict-of-dicts only. The store starts empty on every boot; no
entity is ever seeded. All timestamps read the logical clock, which starts
at exactly 2026-08-01T00:00:00Z and only moves via the test-driving clock
endpoint (never wall-clock time).
"""

import uuid
from datetime import date, datetime, timedelta, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        # Entity tables (keyed by id)
        self.ltas = {}
        self.purchase_orders = {}
        self.fais = {}
        self.characteristics = {}
        self.work_orders = {}
        self.serials = {}
        self.material_certs = {}
        self.sources = {}
        self.process_approvals = {}
        self.ncrs = {}
        self.escape_reports = {}
        self.delegations = {}
        self.spc_measurements = {}
        # Internal bookkeeping
        self._seq = 0
        self._clock = CLOCK_START

    # ---- id / sequence -------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock -------------------------------------------------
    def now(self):
        """Current logical-clock instant (timezone-aware UTC)."""
        return self._clock

    def now_iso(self):
        return fmt_ts(self._clock)

    def today(self):
        return self._clock.date()

    def current_month(self):
        return self._clock.strftime("%Y-%m")

    def set_clock(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._clock = dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso8601(value):
    """Parse an ISO 8601 instant; returns aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z") or text.endswith("z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


db = DB()


def touch(rec):
    """Refresh updated_at and bump the optimistic-concurrency version."""
    rec["updated_at"] = db.now_iso()
    rec["version"] += 1


def base_record(rec_id):
    ts = db.now_iso()
    return {
        "id": rec_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": db.now(),
        "_seq": db.next_seq(),
    }


def public(rec):
    """Strip internal (underscore-prefixed) bookkeeping keys for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_public(records):
    ordered = sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))
    return [public(r) for r in ordered]
