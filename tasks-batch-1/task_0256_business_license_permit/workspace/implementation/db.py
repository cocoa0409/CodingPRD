"""In-memory data store. Per PRD/INSTRUCTION the store starts EMPTY on every boot.

No seeding, no preloaded entities. Every entity is created by the test via the
declared API surface.
"""
import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.activity_categories = {}
        self.businesses = {}
        self.applications = {}
        self.inspections = {}
        self.licenses = {}
        self.endorsements = {}
        self.transfers = {}
        self.fee_assessments = {}
        # Logical server clock (PRD §3.6 / §3.10). Defaults to real now until a
        # LicensingOfficer sets it explicitly. Stored as an aware UTC datetime.
        self.clock_now = datetime.now(timezone.utc)
        self.lock = threading.RLock()

    # ------------------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())


def now_iso(dt=None):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


store = Store()
