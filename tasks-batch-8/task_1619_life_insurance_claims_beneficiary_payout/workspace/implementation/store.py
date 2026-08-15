"""In-memory data store and logical clock.

The store starts completely empty on every boot — no seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z per the PRD and is
only ever advanced through POST /_clock/set_current_utc.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock — never wall-clock time.
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Entity tables, keyed by id (statutes keyed by state_code).
        self.policies = {}
        self.designations = {}
        self.claims = {}
        self.documents = {}
        self.beneficiary_claims = {}
        self.elections = {}
        self.accounts = {}
        self.statutes = {}  # keyed by state_code
        self.matches = {}
        self.cases = {}

    def reset(self):
        self.__init__()


db = Store()
