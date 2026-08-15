"""In-memory data store, logical clock, and monotonic timestamp generator.

The store starts empty on every boot (per-test-server isolation restarts the
process before every test, so a fresh process == a fresh store). Nothing is
seeded, preloaded, or hardcoded here.
"""
import threading
import time
from datetime import datetime, timezone

CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.crossings = {}
        self.localities = {}
        self.teams = {}
        self.reviews = {}
        self.incidents = {}
        self.programs = {}
        self.projects = {}
        self.agreements = {}
        self.qz_applications = {}
        self.qz_members = {}
        self.assignments = {}
        self.work_orders = {}
        self.interconnections = {}
        # Logical clock (PRD §2.5): fixed startup default, moves only via
        # POST /_clock/set_current_utc, never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = CLOCK_DEFAULT_RAW
        # Monotonic timestamp generator state (wall-clock for created_at /
        # updated_at resource metadata).
        self._ts_lock = threading.Lock()
        self._last_ns = 0


store = Store()


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with exactly 3 fractional digits.

    Monotonically non-decreasing per process so created_at ordering is stable.
    """
    with store._ts_lock:
        ns = time.time_ns()
        if ns <= store._last_ns:
            ns = store._last_ns + 1
        store._last_ns = ns
    secs, rem = divmod(ns, 1_000_000_000)
    ms = rem // 1_000_000
    base = datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{ms:03d}Z"
