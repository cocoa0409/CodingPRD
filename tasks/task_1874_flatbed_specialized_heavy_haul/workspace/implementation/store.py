"""In-memory data store. Everything lives in plain dicts; the store starts
empty on every boot — no seeding, no persistence of any kind."""
import threading
import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.loads = {}
        self.securements = {}
        self.permits = {}
        self.escorts = {}
        self.cranes = {}
        self.delays = {}
        self.tickets = {}
        self.fines = {}
        self.invoices = {}
        # Logical clock: fixed default, only moved by POST /_clock/set_current_utc.
        self.clock_str = "2026-08-01T00:00:00Z"
        self.clock_dt = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self._last_ts = None
        self.seq = 0


store = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock UTC timestamp, strictly monotonic within the process so
    created_at ordering is always well defined."""
    with store.lock:
        dt = datetime.now(timezone.utc)
        if store._last_ts is not None and dt <= store._last_ts:
            dt = store._last_ts + timedelta(milliseconds=1)
        store._last_ts = dt
        return fmt_dt(dt)


def next_seq():
    with store.lock:
        store.seq += 1
        return store.seq


def new_entity():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1
