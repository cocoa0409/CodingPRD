"""In-memory data store and time helpers.

The store starts EMPTY on every boot; every entity is created by clients through
the declared endpoints. Nothing is seeded, preloaded or persisted to disk.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

from constants import DEFAULT_CLOCK_ISO

UTC = timezone.utc


def parse_iso(text):
    """Parse an ISO 8601 instant, normalised to UTC. Raises ValueError."""
    if not isinstance(text, str):
        raise ValueError("not a string")
    raw = text.strip()
    if not raw:
        raise ValueError("empty")
    body = raw
    if body.endswith("Z") or body.endswith("z"):
        body = body[:-1] + "+00:00"
    dt = datetime.fromisoformat(body)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


DEFAULT_CLOCK = parse_iso(DEFAULT_CLOCK_ISO)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.funding_agreements = {}
        self.stations = {}
        self.pressure_vessels = {}
        self.production_assets = {}
        self.power_contracts = {}
        self.production_lots = {}
        self.purity_tests = {}
        self.ledger_entries = {}
        self.deliveries = {}
        self.dispense_sessions = {}
        self.safety_events = {}
        self.responder_certs = {}
        self.incentive_claims = {}
        self.uptime_reports = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self._ledger_seq = {}
        self._last_ts = None

    # ---- identity / timestamps ----
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def now(self):
        """Strictly increasing wall-clock UTC instant truncated to milliseconds.

        Used only for created_at / updated_at / envelope timestamps; every
        business decision reads the logical clock instead (PRD 2.5).
        """
        raw = datetime.now(UTC)
        ts = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
        if self._last_ts is not None and ts <= self._last_ts:
            ts = self._last_ts + _ONE_MS
        self._last_ts = ts
        return ts

    def next_ledger_sequence(self, station_id):
        nxt = self._ledger_seq.get(station_id, 0) + 1
        self._ledger_seq[station_id] = nxt
        return nxt


from datetime import timedelta  # noqa: E402

_ONE_MS = timedelta(milliseconds=1)

db = Store()


def base_row(with_common=True):
    """id + created_at (+ updated_at/version when the entity has common fields)."""
    row = {
        "id": db.new_id(),
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }
    if with_common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version by one (PRD 2.4)."""
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 1) + 1
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
