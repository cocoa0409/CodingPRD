"""In-memory data store. Every dict starts empty on boot.

Store keyed by id -> entity dict. `logical_clock` defaults to the PRD-declared
default 2026-03-01T00:00:00Z and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

customers = {}         # id -> Customer
plans = {}             # id -> Plan
subscriptions = {}     # id -> Subscription
shipments = {}         # id -> Shipment
stem_lots = {}         # id -> StemLot
allocations = {}       # id -> StemAllocation
carrier_routes = {}    # id -> CarrierRoute
charges = {}           # id -> Charge
wallet_entries = {}    # id -> WalletEntry
win_back_offers = {}   # id -> WinBackOffer
substitution_rules = {}  # id -> SubstitutionRule

logical_clock = DEFAULT_CLOCK


def reset():
    """Reset all state; used only in tests (not exposed via HTTP)."""
    global logical_clock
    customers.clear()
    plans.clear()
    subscriptions.clear()
    shipments.clear()
    stem_lots.clear()
    allocations.clear()
    carrier_routes.clear()
    charges.clear()
    wallet_entries.clear()
    win_back_offers.clear()
    substitution_rules.clear()
    logical_clock = DEFAULT_CLOCK


def now():
    """Return the current logical clock instant."""
    return logical_clock


def set_clock(dt):
    global logical_clock
    logical_clock = dt
