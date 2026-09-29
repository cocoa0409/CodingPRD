"""In-memory store.  Nothing is ever seeded: every collection starts empty and
only client requests put rows in it."""
import threading
import uuid
from datetime import datetime, timezone

import config

COLLECTIONS = (
    "dairies",
    "facilities",
    "agreements",
    "deliveries",
    "ops_days",
    "interconnects",
    "nominations",
    "pathways",
    "batches",
    "audits",
    "applications",
    "statements",
)


def _parse_iso(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = _parse_iso(config.CLOCK_DEFAULT_ISO)

    # -- logical clock -------------------------------------------------------
    def now_logical(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # -- rows ----------------------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_row(self, extra=None):
        now = datetime.now(timezone.utc)
        row = {
            "id": str(uuid.uuid4()),
            "_created": now,
            "_updated": now,
            "_seq": self.next_seq(),
            "version": 1,
        }
        if extra:
            row.update(extra)
        return row

    def touch(self, row, bumps=1):
        row["_updated"] = datetime.now(timezone.utc)
        row["version"] = row.get("version", 1) + bumps
        return row


db = Store()


def sorted_rows(collection):
    return sorted(collection.values(), key=lambda r: (r["_created"], r["_seq"]))
