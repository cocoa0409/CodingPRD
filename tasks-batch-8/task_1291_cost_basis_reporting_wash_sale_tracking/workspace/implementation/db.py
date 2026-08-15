"""In-memory data store. Store starts empty on every boot — no seeding."""

import os
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso3(dt):
    """Format datetime as ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return s


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _parse_iso(_DEFAULT_CLOCK)
        self.firms = {}
        self.customers = {}
        self.accounts = {}
        self.securities = {}
        self.tax_lots = {}
        self.dispositions = {}
        self.corporate_actions = {}
        self.transfer_statements = {}
        self.wash_sale_events = {}
        self.tax_forms = {}
        self.basis_change_requests = {}

    # -- clock ---------------------------------------------------------------
    def now_iso(self):
        return _iso3(self.clock)

    def set_clock(self, iso_str):
        self.clock = _parse_iso(iso_str)

    # -- id minting ------------------------------------------------------------
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    @staticmethod
    def new_request_id():
        return "req_" + uuid.uuid4().hex[:24]


# A single global store instance. The test harness restarts the process before
# every test, so a module-level store is fine and keeps things simple.
store = Store()
