"""In-memory data store.

All state lives in module-level dicts keyed by id. NOTHING is seeded at import
time — every collection starts empty on each process boot. The test harness
restarts the server (start.sh) before every test, which wipes all state.

Common system fields (PRD §2.4):
  - Full quartet: id, created_at, updated_at, version
  - Lean entities (TankMonitorReading, DegreeDayReading): only id, created_at
"""
import uuid

from clock import clock_now_iso

# One dict per entity collection, keyed by id.
accounts = {}
price_plans = {}
tanks = {}
tank_readings = {}
degree_day_readings = {}
market_prices = {}
tank_leases = {}
safety_inspections = {}
trucks = {}
routes = {}
delivery_orders = {}
budget_plans = {}


def new_id():
    return str(uuid.uuid4())


def stamp_create_full(record):
    """Attach the full system quartet (id/created_at/updated_at/version)."""
    ts = clock_now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def stamp_create_lean(record):
    """Attach only id + created_at (immutable observation entities)."""
    record["id"] = new_id()
    record["created_at"] = clock_now_iso()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    record["updated_at"] = clock_now_iso()
    record["version"] = record.get("version", 1) + 1


def touch_no_version(record):
    """Refresh updated_at without bumping version.

    Used for account mutations that the PRD does NOT mark as version increments
    (budget installment / reconcile credit_balance changes). Per PRD §2.7 only
    deliver and reverse advance Account.version, and the OCC check relies on
    that, so installment/reconcile must not bump it.
    """
    record["updated_at"] = clock_now_iso()
