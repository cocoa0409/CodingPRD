"""In-memory data store for REIT Compliance & Distribution Management.

The store starts completely empty on every boot — no seeding, no preloading.
The logical clock starts at exactly 2026-08-01T00:00:00Z and is only advanced
via POST /_clock/set_current_utc; it never falls back to wall-clock time.
"""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Entity tables: id -> dict
        self.reits = {}
        self.asset_holdings = {}
        self.income_items = {}
        self.quarters = {}
        self.asset_test_reports = {}
        self.income_test_reports = {}
        self.shareholders = {}
        self.shareholder_snapshots = {}
        self.shareholder_positions = {}
        self.distribution_requirements = {}
        self.dividend_declarations = {}
        self.ep_adjustments = {}
        self.asset_sales = {}
        self.compliance_disclosures = {}
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z
        self.current_utc = "2026-08-01T00:00:00Z"


db = Store()
