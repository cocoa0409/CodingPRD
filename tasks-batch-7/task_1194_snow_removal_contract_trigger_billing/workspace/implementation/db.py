"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts empty on every boot — no seeding, no preloading.
"""
import uuid
from datetime import datetime, timezone, timedelta


def _new_id():
    return str(uuid.uuid4())


def _now_iso():
    """Return current logical clock time as ISO 8601 UTC with 3 fractional digits."""
    return _logical_clock.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_logical_clock.microsecond // 1000:03d}Z"


def _parse_iso(s):
    """Parse ISO 8601 datetime string to datetime object."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try without timezone
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%f")
                dt = dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_iso(dt):
    """Convert datetime to ISO 8601 UTC string with 3 fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Logical clock — fixed startup default
_logical_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt


def now_iso():
    return _to_iso(_logical_clock)


# ---- In-memory stores (all start empty) ----

class Store:
    """Generic in-memory store for one entity type."""

    def __init__(self):
        self._data = {}

    def create(self, obj):
        self._data[obj["id"]] = obj
        return obj

    def get(self, entity_id):
        return self._data.get(entity_id)

    def list_all(self):
        return list(self._data.values())

    def update(self, entity_id, obj):
        self._data[entity_id] = obj
        return obj

    def delete(self, entity_id):
        self._data.pop(entity_id, None)

    def filter(self, **kwargs):
        results = []
        for obj in self._data.values():
            match = True
            for k, v in kwargs.items():
                if obj.get(k) != v:
                    match = False
                    break
            if match:
                results.append(obj)
        return results

    def clear(self):
        self._data.clear()


# Entity stores
clients = Store()
sites = Store()
contracts = Store()
contract_sites = Store()
amendments = Store()
storm_events = Store()
observations = Store()
visits = Store()
materials = Store()
photos = Store()
invoices = Store()
disputes = Store()
claims = Store()
subcontractors = Store()
coverage_assignments = Store()
true_ups = Store()


def reset_all():
    """Reset all stores (for testing)."""
    clients.clear()
    sites.clear()
    contracts.clear()
    contract_sites.clear()
    amendments.clear()
    storm_events.clear()
    observations.clear()
    visits.clear()
    materials.clear()
    photos.clear()
    invoices.clear()
    disputes.clear()
    claims.clear()
    subcontractors.clear()
    coverage_assignments.clear()
    true_ups.clear()
    global _logical_clock
    _logical_clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
