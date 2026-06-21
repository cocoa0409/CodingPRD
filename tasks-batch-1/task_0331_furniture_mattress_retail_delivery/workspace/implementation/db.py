"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by UUID id. Nothing is seeded at
import time; every entity is created by a request handler. Because the store is
process-memory only, a fresh `python3 app.py` boot (as the per-test-server
isolation harness does before each test) starts with a completely empty store.
"""
import itertools
import uuid

# One dict per entity type, keyed by id.
customers = {}
products = {}
orders = {}
order_lines = {}
financing_plans = {}
payments = {}
delivery_routes = {}
delivery_stops = {}
protection_plans = {}
return_requests = {}

# Monotonic sequence to break created_at ties for stable ascending sort.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())
