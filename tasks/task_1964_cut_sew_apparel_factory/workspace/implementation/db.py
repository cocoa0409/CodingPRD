"""In-memory data store (PRD §2.4).

The store starts empty on every boot — no seeding of any kind. Every entity
any caller needs is constructed through the declared API surface. Storage is
plain Python dicts keyed by id; a fresh `start.sh` invocation wipes all state.
"""

import threading
import uuid
from datetime import datetime, timezone, timedelta


def parse_date(value):
    """Strict YYYY-MM-DD calendar date; raises ValueError otherwise."""
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("not a YYYY-MM-DD string")
    dt = datetime.strptime(value, "%Y-%m-%d")
    if dt.strftime("%Y-%m-%d") != value:
        raise ValueError("not a zero-padded YYYY-MM-DD string")
    return dt.date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.2/§2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # One global request lock: cascades touch many resources per request,
        # so all requests are serialized (complexity_profile consistency_model:
        # immediate).
        self.lock = threading.RLock()
        self._ts_lock = threading.Lock()
        self._last_ts = None
        self._seq_lock = threading.Lock()
        self._seq = 0
        # Entity tables — all start empty.
        self.styles = {}
        self.tech_packs = {}
        self.operation_specs = {}
        self.trim_items = {}
        self.trim_requirements = {}
        self.fabric_rolls = {}
        self.production_orders = {}
        self.markers = {}
        self.bundles = {}
        self.sewing_lines = {}
        self.line_assignments = {}
        self.operators = {}
        self.piece_work_entries = {}
        self.payroll_runs = {}
        self.quality_audits = {}
        # Creation ordinal for ProductionOrder (drives bundle ticket_no).
        self._order_seq = 0

    def now(self):
        """Strictly increasing UTC clock at 1ms resolution.

        Guarantees created_at uniqueness per creation request (relied on by
        payroll remainder allocation, SCAFFOLD calculations.payroll_run_totals).
        """
        with self._ts_lock:
            now = datetime.now(timezone.utc)
            now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
            if self._last_ts is not None and now <= self._last_ts:
                now = self._last_ts + timedelta(milliseconds=1)
            self._last_ts = now
            return now

    def now_str(self):
        return fmt_ts(self.now())

    def next_seq(self):
        """Monotonic arrival counter; deterministic created_at tiebreak."""
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def next_order_seq(self):
        with self._seq_lock:
            self._order_seq += 1
            return self._order_seq


store = Store()
