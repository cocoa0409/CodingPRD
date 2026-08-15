"""In-memory data store, logical clock, and shared constants (PRD §2.4, §2.5)."""

import uuid
from datetime import datetime, timezone

# --- Size codes (PRD §2.8) ---
SIZE_CODES = [
    "NEWBORN", "SIZE_1", "SIZE_2", "SIZE_3",
    "SIZE_4", "SIZE_5", "SIZE_6", "TRAINING_PANTS",
]

ROLES = [
    "BankAdmin", "WarehouseManager", "FinanceManager", "AgencyCoordinator",
    "PrivacyOfficer", "VolunteerCoordinator", "Volunteer",
]

# --- Calculation constants (scaffold §1.3 / PRD §3) ---
FAIR_MARKET_CENTS = {
    "NEWBORN": 35, "SIZE_1": 32, "SIZE_2": 30, "SIZE_3": 28,
    "SIZE_4": 26, "SIZE_5": 24, "SIZE_6": 22, "TRAINING_PANTS": 40,
}
BASE_FLOOR_UNITS = 100
CAPACITY_CAP_FRACTION_NUM = 1   # 0.5 as a fraction: 1/2
CAPACITY_CAP_FRACTION_DEN = 2
UNITS_PER_CHILD_PER_MONTH = 50
TRAILING_WINDOW_DAYS = 28
DONATION_WINDOW_DAYS = 90
WEEKS_IN_WINDOW = 4


class Store:
    """The entire database. Starts empty on every boot; no seeding."""

    def __init__(self):
        self.partner_agencies = {}      # id -> dict
        self.grants = {}                # id -> dict
        self.inventory = None           # singleton dict or None
        self.intake_batches = {}        # id -> dict
        self.purchase_orders = {}       # id -> dict
        self.allocation_runs = {}       # id -> dict
        self.allocation_lines = {}      # id -> dict
        self.distribution_events = {}   # id -> dict
        self.issuances = {}             # id -> dict
        self.households = {}            # id -> dict
        self.volunteer_shifts = {}      # id -> dict
        # Logical clock (PRD §2.4): starts exactly at 2026-08-01T00:00:00Z,
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical-clock instant."""
    return store.clock


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.5)."""
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return s[:-3] + "Z"


def touch(entity):
    """Stamp updated_at and bump version for a mutated resource (PRD §2.5).

    Exactly one increment per resource per request: callers mutate the entity
    dict first, then call touch() once.
    """
    entity["updated_at"] = now()
    entity["version"] += 1


def base_fields():
    """Common system-managed fields for a new resource (PRD §2.5)."""
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


def current_month():
    """Calendar month (UTC) of the logical clock as 'YYYY-MM'."""
    c = store.clock
    return "%04d-%02d" % (c.year, c.month)
