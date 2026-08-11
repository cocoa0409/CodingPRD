"""In-memory data store and the logical clock (PRD §2.4, §2.5).

Storage is plain Python dicts keyed by id. Nothing is seeded at startup:
every table begins empty on every process boot. The logical clock starts at
exactly 2026-05-01T00:00:00Z and is only moved by the test-driving endpoint.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock — deterministic default, never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # global monotonic insertion counter (created_at tie-break)
        self.plans = {}
        self.freeze_windows = {}
        self.participants = {}
        self.accounts = {}
        self.msb = {}  # MoneySourceBalance rows
        self.loans = {}
        self.cases = {}
        self.documents = {}
        self.verifications = {}
        self.disbursements = {}
        self.redeposits = {}
        self.notices = {}
        self.taxforms = {}


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Logical-clock timestamp used for created_at / updated_at / verified_at / offset_at."""
    return fmt_ts(store.clock)


def wallclock_iso():
    """Wall-clock timestamp used only for meta.api_request_timestamp."""
    return fmt_ts(datetime.now(timezone.utc))


def clock_date():
    return store.clock.date()


def create_entity(table, fields):
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    table[ent["id"]] = ent
    return ent


def touch(ent):
    """Every mutation refreshes updated_at and increments version by exactly 1 (PRD §2.5)."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def strip_internal(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}
