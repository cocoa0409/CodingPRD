"""In-memory data store.

Each entity is stored in its own dict keyed by id. The store starts empty
on every process boot — tests build all required state via the public API.
"""
from threading import RLock


lock = RLock()

members = {}              # id -> dict
properties = {}
hosts = {}
host_assignments = {}
gaming_sessions = {}
comp_room_bookings = {}
self_exclusions = {}
velocity_alerts = {}
annual_reset_runs = {}


def reset() -> None:
    for store in (
        members,
        properties,
        hosts,
        host_assignments,
        gaming_sessions,
        comp_room_bookings,
        self_exclusions,
        velocity_alerts,
        annual_reset_runs,
    ):
        store.clear()
