"""In-memory data store. Starts empty on every boot; no seeding, no persistence."""
from datetime import datetime, timezone

cost_centers = {}
job_roles = {}
items = {}
contract_prices = {}
issuance_policies = {}
employees = {}
machines = {}
slots = {}
units = {}
overrides = {}
issuances = {}
restock_orders = {}
service_tickets = {}
batches = {}
audits = {}

# Logical clock: startup default exactly 2026-05-01T00:00:00Z; never wall-clock.
clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
