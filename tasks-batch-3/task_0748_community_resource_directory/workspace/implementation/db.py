"""In-memory data store. Starts empty on every boot."""
from datetime import datetime, timezone


class DB:
    def __init__(self) -> None:
        # Logical clock — starts at exactly 2026-03-01T00:00:00Z on every boot.
        self.clock: datetime = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

        self.funders: dict = {}
        self.providers: dict = {}
        self.programs: dict = {}
        self.availability_windows: dict = {}
        self.clients: dict = {}
        self.intakes: dict = {}
        self.consent_grants: dict = {}
        self.referrals: dict = {}
        self.transport_plans: dict = {}
        self.outcome_reports: dict = {}
        self.funder_reports: dict = {}

    def reset(self) -> None:
        self.__init__()


db = DB()
