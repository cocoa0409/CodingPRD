"""In-memory data store. State lives only in module-level dicts; every boot
starts completely empty (no seeding). The logical clock defaults to exactly
2026-08-01T00:00:00Z and only moves via POST /api/_clock/set_current_utc."""

import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

properties = {}
surveys = {}
product_models = {}
technicians = {}
contractors = {}
projects = {}
permits = {}
work_orders = {}
units = {}
inspections = {}
certificates = {}
contracts = {}
service_calls = {}
grant_programs = {}
grant_applications = {}
change_orders = {}

_seq_counter = itertools.count(1)
_clock = {"now": DEFAULT_CLOCK}


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def touch(rec):
    """Bump optimistic-concurrency version and refresh updated_at (logical clock)."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()


def new_record(fields):
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    rec.update(fields)
    rec["_seq"] = next_seq()
    return rec
