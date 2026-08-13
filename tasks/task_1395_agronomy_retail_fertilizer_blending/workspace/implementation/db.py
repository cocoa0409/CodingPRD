"""In-memory data store.

Everything lives in module-level dicts. The store starts EMPTY on every boot:
no seeding, no preloading. The logical clock starts at 2026-08-01T00:00:00Z
and never falls back to wall-clock time.
"""

from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _START_CLOCK

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt


CLOCK = LogicalClock()

# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

growers = {}            # GrowerAccount
fields = {}             # Field
soil_tests = {}         # SoilTest
recommendations = {}    # Recommendation
nutrient_plans = {}     # NutrientManagementPlan
permits = {}            # EnvironmentalPermit
products = {}           # Product
price_sheets = {}       # PriceSheet
inventory_lots = {}     # InventoryLot
prepay_programs = {}    # PrepayProgram
prepay_contracts = {}   # PrepayContract
blend_orders = {}       # BlendOrder
blend_lines = {}        # BlendLine
blenders = {}           # Blender
blend_batches = {}      # BlendBatch
trucks = {}             # Truck
delivery_routes = {}    # DeliveryRoute
delivery_stops = {}     # DeliveryStop
ledger_entries = {}     # CreditLedgerEntry (append-only)

# Order reservations: order_id -> list of (lot_id, tons) recorded at book time
order_reservations = {}

# Payments allocated to an order so far: order_id -> cents
order_payments_applied = {}
