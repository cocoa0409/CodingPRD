"""In-memory data store, logical clock and record helpers.

Storage is process-local and starts completely EMPTY on every boot.  No entity
is ever seeded, preloaded or hardcoded here.
"""

import threading
import uuid
from datetime import datetime, timezone

UTC = timezone.utc

# PRD 2.5 - the logical clock reads exactly this instant before any client moves it.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
INITIAL_CLOCK_RAW = "2026-08-01T00:00:00.000Z"

COLLECTIONS = (
    "creditors",
    "debtors",
    "judgments",
    "county_filings",
    "asset_findings",
    "enforcement_actions",
    "exemption_claims",
    "debtor_examinations",
    "settlement_offers",
    "installment_agreements",
    "payments",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = INITIAL_CLOCK
        self.clock_raw = INITIAL_CLOCK_RAW
        self._seq = 0
        self._last_ms = 0

    # ---- ordering / timestamps -------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def now_iso(self):
        """Strictly increasing wall-clock ISO-8601 UTC stamp, millisecond precision.

        Monotonicity guarantees that `created_at ASC` is exactly insertion order,
        which every cascade in the PRD relies on.
        """
        ms = int(datetime.now(UTC).timestamp() * 1000)
        if ms <= self._last_ms:
            ms = self._last_ms + 1
        self._last_ms = ms
        base = datetime.fromtimestamp(ms // 1000, UTC)
        return base.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)

    # ---- logical clock ----------------------------------------------------
    def clock_date(self):
        return self.clock.date()


store = Store()


def fmt_instant(dt):
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    return None if d is None else d.isoformat()


def new_row(fields):
    ts = store.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at only (PRD 2.4: any mutation refreshes updated_at)."""
    row["updated_at"] = store.now_iso()
    return row


def bump(row):
    """Refresh updated_at and increment version by exactly one."""
    row["updated_at"] = store.now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
