"""In-memory data store. All dicts keyed by id. No persistence."""

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


class Store:
    def __init__(self):
        self.rent_cap_policies: dict = {}
        self.properties: dict = {}
        self.units: dict = {}
        self.residents: dict = {}
        self.leases: dict = {}
        self.renewal_offers: dict = {}
        self.concession_approvals: dict = {}
        self.non_renewal_notices: dict = {}
        self.renewal_documents: dict = {}
        # Logical clock — default before any set call
        self.clock_iso: str = "2026-05-01T00:00:00Z"


store = Store()
