"""In-memory data store. Starts empty on every boot — never seeded."""
from datetime import datetime, timezone

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z; never falls
# back to wall-clock time.
CLOCK_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Entity stores, keyed by id.
sites = {}
facilities = {}
renters = {}
policies = {}
calendar_events = {}
requests = {}
certificates = {}
permits = {}
work_orders = {}
invoices = {}
damage_assessments = {}
payments = {}
seasonal_permits = {}

# Idempotency ledger: key -> (payload-signature, payment_id)
idempotency = {}
