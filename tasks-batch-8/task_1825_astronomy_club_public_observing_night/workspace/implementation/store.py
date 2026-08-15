"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: pinned default at process startup, never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0  # global insertion sequence for stable created_at ordering

        self.tiers = {}        # MembershipTier
        self.members = {}      # Member
        self.invoices = {}     # DuesInvoice
        self.payments = {}     # DuesPayment (append-only: no updated_at/version)
        self.telescopes = {}   # Telescope
        self.certs = {}        # TrainingCertification
        self.loans = {}        # LoanReservation
        self.tickets = {}      # MaintenanceTicket
        self.events = {}       # ObservingEvent
        self.assignments = {}  # EventOperatorAssignment
        self.bookings = {}     # GroupVisitBooking
        self.readings = {}     # SkyQualityReading (append-only)
        self.reports = {}      # DarkSkyReport
        self.no_show_marks = []  # [{member_id, marked_at, entity_created_at, seq}]

    def next_seq(self):
        self.seq += 1
        return self.seq


DB = Store()
