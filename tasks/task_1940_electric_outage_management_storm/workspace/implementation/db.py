"""In-memory data store + server-side logical clock.

Storage is in-memory only: plain Python dicts keyed by id. No file persistence,
no seeding. The store starts empty on every boot.

Logical clock: before any set call, reads exactly 2026-08-01T00:00:00Z and
never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone


DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.storm_events = {}
        self.feeders = {}
        self.priority_customers = {}
        self.trouble_signals = {}
        self.outages = {}
        self.etr_revisions = {}
        self.damage_assessments = {}
        self.crews = {}
        self.mutual_aid_crews = {}
        self.lodging_blocks = {}
        self.work_orders = {}
        self.switching_orders = {}
        self.material_stocks = {}
        self.material_requisitions = {}
        self.cost_ledger_entries = {}
        self.fema_claims = {}
        # lodging assignment facts: list of dicts recorded at assign time
        # {block_id, crew_id, roster_size, window_start, window_end, created_at, seq}
        self.lodging_assignments = []
        self._now = DEFAULT_NOW
        self._req_counter = 0
        self._mono_seq = 0

    # ---- logical clock ----
    def now(self):
        return self._now

    def set_now(self, dt):
        self._now = dt

    # ---- ids / request ids ----
    def new_id(self):
        return str(uuid.uuid4())

    def next_req_id(self):
        self._req_counter += 1
        return f"req_{uuid.uuid4().hex[:20]}"

    def next_mono(self):
        """Monotonic tie-break sequence for created_at-equal ordering."""
        self._mono_seq += 1
        return self._mono_seq


db = Store()


def now_iso():
    """Logical now serialized as ISO 8601 UTC with three fractional digits."""
    return iso_ms(db.now())


def iso_ms(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' or explicit offsets, with/without fractional seconds.
    Returns None if unparseable.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
