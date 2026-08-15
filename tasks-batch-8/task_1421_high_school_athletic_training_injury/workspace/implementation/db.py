"""In-memory data store. Starts empty on every boot; nothing is seeded."""
import threading

lock = threading.RLock()

# Logical clock; never falls back to wall-clock time.
current_utc_iso = "2026-08-01T00:00:00Z"

staff = {}
athletes = {}
physicals = {}
baselines = {}
venues = {}
eaps = {}
events = {}
assignments = {}
readings = {}
injuries = {}
referrals = {}
protocols = {}
notifications = {}
supply_items = {}
inventory_txns = {}
restock_orders = {}
budgets = {}
