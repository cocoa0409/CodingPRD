"""In-memory data store. Store starts empty on every boot; no seeding."""
import threading
from datetime import datetime, timezone


def _epoch_start():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        # Logical clock: starts at exactly 2026-08-01T00:00:00Z; moves only via
        # POST /_clock/set_current_utc. Never falls back to wall-clock time.
        self.clock = _epoch_start()
        self.partners = {}        # NonprofitPartner
        self.events = {}          # ServiceEvent
        self.projects = {}        # ServiceProject
        self.volunteers = {}      # EmployeeVolunteer
        self.registrations = {}   # Registration
        self.orders = {}          # ProcurementOrder
        self.vehicles = {}        # Vehicle
        self.manifests = {}       # TransportManifest
        self.meal_plans = {}      # MealPlan
        self.assignments = {}     # SupervisionAssignment
        self.sponsorships = {}    # Sponsorship
        self.impacts = {}         # ImpactRecord
        self.surveys = {}         # FeedbackSurvey

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        """Current logical clock instant."""
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()
