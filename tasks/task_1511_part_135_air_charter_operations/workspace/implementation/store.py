"""In-memory data store and logical clock.

The store starts empty on every boot. No entity seeding happens here or
anywhere else at startup -- every entity is created via the declared API.
"""

import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables keyed by id. Values are plain dicts.
        self.owners = {}                # AircraftOwner
        self.aircraft = {}              # Aircraft
        self.crew_members = {}          # CrewMember
        self.trips = {}                 # TripRequest
        self.quote_legs = {}            # QuoteLeg
        self.aircraft_assignments = {}  # AircraftAssignment
        self.crew_assignments = {}      # CrewAssignment
        self.maintenance_windows = {}   # MaintenanceWindow
        self.passengers = {}            # Passenger
        self.permits = {}               # OverflightPermit
        self.payments = {}              # Payment (append-only ledger)
        self.flight_logs = {}           # FlightLog (append-only ledger)
        self.statements = {}            # OwnerStatement
        self.findings = {}              # ComplianceFinding
        self.advisories = {}            # WeatherAdvisory (append-only)

        # Monotonic insertion sequence for stable created_at tie-breaking.
        self.seq = itertools.count(1)

        # Logical clock: reads exactly 2026-08-01T00:00:00Z before any
        # clock-setting call (PRD section 2.4); never uses wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self.seq)


# Module-level singleton. A fresh process gets a fresh, empty store.
db = Store()
