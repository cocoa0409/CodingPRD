"""In-memory data store. Starts empty on every boot; nothing is seeded."""
import itertools
import threading
from datetime import datetime, timezone

lock = threading.RLock()
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Entity tables, keyed by id.
policyholders = {}
repair_shops = {}
rental_partners = {}
claims = {}
verifications = {}
repair_orders = {}
milestones = {}
reservations = {}
extension_requests = {}
class_changes = {}
lou_claims = {}
invoices = {}
recovery_cases = {}
communication_logs = {}

# Logical clock. Before any call it reads exactly 2026-08-01T00:00:00Z and never
# falls back to wall-clock time.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def clock_date():
    return _clock.date()


def set_clock(dt):
    global _clock
    _clock = dt
