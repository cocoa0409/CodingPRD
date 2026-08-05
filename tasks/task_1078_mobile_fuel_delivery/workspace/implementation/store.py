"""In-memory data store, logical clock, id/sequence generation, and constants.

All state is process-local and rebuilt from scratch on every boot. Nothing is
seeded here — every entity is created by the API surface at test time.
"""
import uuid
from datetime import datetime, timezone, timedelta

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Domain constants (from PRD §3 / scaffold calculations)
# ---------------------------------------------------------------------------
UNUSED_DELIVERY_CREDIT_CENTS = 400
MEMBERSHIP_PERIOD_DAYS = 30
BASE_DELIVERY_FEE_CENTS = 1200
MEMBER_OVERAGE_FEE_CENTS = 600
PRIORITY_SURCHARGE_CENTS = 500
CAR_WASH_PRICE_CENTS = 1595
OIL_CHANGE_PRICE_CENTS = 6495
MEMBER_ADDON_DISCOUNT_PCT = "0.10"          # decimal string
MEMBER_DISCOUNT_PER_GALLON_CENTS = 10
SERVICE_BUFFER_MINUTES = 60

ROLES = {"PlatformAdmin", "Dispatcher", "Driver", "FleetManager", "Member", "BillingOfficer"}
FUEL_TYPES = {"REGULAR", "PREMIUM", "DIESEL"}
ZONES = {"ZONE_A", "ZONE_B"}
ADDON_TYPES = {"CAR_WASH", "OIL_CHANGE"}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


class _State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.memberships = {}
        self.fleet_accounts = {}
        self.vehicles = {}
        self.trucks = {}
        self.compartments = {}
        self.routes = {}
        self.orders = {}
        self.addons = {}
        self.fuel_prices = {}
        self._clock = DEFAULT_CLOCK
        self._seq = 0

    # -- logical clock --
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    # -- monotonic insertion sequence (stable ordering + tie-breaks) --
    def next_seq(self):
        self._seq += 1
        return self._seq


DB = _State()


def new_id():
    return str(uuid.uuid4())


def now():
    return DB.now()
