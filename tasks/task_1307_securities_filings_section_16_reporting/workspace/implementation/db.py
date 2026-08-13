"""In-memory data store. The store starts empty on every boot — no seeding."""
from datetime import datetime, timezone


def _utc_now_iso():
    """Current wall-clock time, ISO8601 with 3 fractional digits, Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.issuers = {}
        self.reporting_persons = {}
        self.transactions = {}
        self.filings = {}
        self.trading_plans = {}
        self.blackout_windows = {}
        self.beneficial_holders = {}
        self.position_changes = {}
        self.annual_sweeps = {}
        self.filing_agent_authorizations = {}
        # Logical clock: default 2026-08-01T00:00:00Z (PRD §2.5)
        self.clock = "2026-08-01T00:00:00Z"


db = Store()
