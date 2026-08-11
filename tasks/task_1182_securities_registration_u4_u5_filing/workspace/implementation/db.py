"""In-memory data store. The store starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.firms = {}
        self.applicants = {}
        self.registration_requests = {}
        self.jurisdiction_selections = {}
        self.fingerprint_submissions = {}
        self.background_disclosures = {}
        self.exam_requirements = {}
        self.exam_windows = {}
        self.disclosure_events = {}
        self.amendment_filings = {}
        self.termination_filings = {}
        self.u5_comments = {}
        self.affiliation_requests = {}
        self.renewal_invoices = {}
        self.regulatory_inquiries = {}
        # Logical clock: fixed startup default 2026-05-01T00:00:00Z, never wall-clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_echo = "2026-05-01T00:00:00Z"
        self.seq = 0  # global insertion counter for stable ordering


store = Store()


def new_id():
    return str(uuid.uuid4())
