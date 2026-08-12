import itertools
from datetime import datetime, timezone

# In-memory stores: id -> record dict. Fresh on every process boot; never seeded.
owners = {}
pets = {}
veterinarians = {}
drug_catalog_items = {}
flavorings = {}
formulas = {}
prescriptions = {}
compound_orders = {}
lots = {}
lot_allocations = {}
benches = {}
bench_reservations = {}
shipments = {}
temperature_readings = {}
cooler_assets = {}
wellness_plans = {}
enrollments = {}
insurance_policies = {}
claims = {}
auto_ship_schedules = {}
cs_entries = {}
recalls = {}
recall_tasks = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Logical clock: starts exactly at 2026-05-01T00:00:00Z and never falls back
# to wall-clock time.
_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
