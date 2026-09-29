"""In-memory store, id minting, row sequence timestamps and the logical clock.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded; every row is created through a declared endpoint.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

CLOCK_INITIAL = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC timestamp. Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    # ---------------------------------------------------------------- lifecycle
    def reset(self):
        self.designs = {}
        self.allocations = {}
        self.lots = {}
        self.work_orders = {}
        self.instruments = {}
        self.runs = {}
        self.reports = {}
        self.chambers = {}
        self.coating_runs = {}
        self.assemblies = {}
        self.components = {}
        self.inspections = {}
        self.classifications = {}
        self.packages = {}

        self.clock_str = CLOCK_INITIAL
        self.clock_dt = parse_iso(CLOCK_INITIAL)

        self._seq = 0
        self._base_dt = datetime.now(timezone.utc).replace(microsecond=0)
        self._touched = set()

    def begin_request(self):
        self._touched = set()

    # ------------------------------------------------------------ row sequence
    def _next_ts(self):
        """Server row sequence: strictly increasing, millisecond resolution."""
        self._seq += 1
        return self._seq, fmt_iso3(self._base_dt + timedelta(milliseconds=self._seq))

    def new_row(self):
        seq, ts = self._next_ts()
        return {
            "id": str(uuid.uuid4()),
            "_seq": seq,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }

    def touch(self, row):
        """Refresh updated_at; bump version once per row per request."""
        _seq, ts = self._next_ts()
        row["updated_at"] = ts
        if row["id"] not in self._touched:
            self._touched.add(row["id"])
            row["version"] = int(row["version"]) + 1

    # -------------------------------------------------------------------- clock
    def now_str(self):
        return self.clock_str

    def now_dt(self):
        return self.clock_dt

    def set_clock(self, raw, dt):
        previous = self.clock_str
        self.clock_str = raw
        self.clock_dt = dt
        return previous


store = Store()


def ordered(rows):
    """created_at ascending == row sequence ascending (a total order)."""
    return sorted(rows, key=lambda r: r["_seq"])


def enc(value):
    """JSON encoding of stored values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: enc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [enc(v) for v in value]
    return value


def public(row):
    return {k: enc(v) for k, v in row.items() if not k.startswith("_")}
