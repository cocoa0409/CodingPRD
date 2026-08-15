"""In-memory data store and logical clock. Starts empty on every boot."""
import itertools
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

# Logical clock: starts at exactly 2026-08-01T00:00:00Z and never reads the
# wall clock. Set only via POST /api/_clock/set_current_utc.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# Global insertion sequence: breaks created_at ties so list ordering and
# "oldest first" waterfalls are deterministic even when the logical clock
# is frozen (all created_at values equal).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Entity tables: dicts keyed by id. All start empty — nothing is seeded.
growers = {}
contracts = {}
houses = {}
flocks = {}
placements = {}
feed_deliveries = {}
mortality_reports = {}
catch_schedules = {}
catch_crews = {}
weight_tickets = {}
audits = {}
settlement_groups = {}
settlements = {}
loans = {}
