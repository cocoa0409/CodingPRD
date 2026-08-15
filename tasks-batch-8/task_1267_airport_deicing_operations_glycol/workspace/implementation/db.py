"""In-memory data store and logical clock.

The store starts empty on every boot. Nothing is seeded, preloaded, or
hardcoded. All entities are constructed via the declared API surface.
"""
import threading
from datetime import datetime, timezone

_lock = threading.RLock()

# Logical clock: startup default is exactly 2026-05-01T00:00:00Z.
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def get_clock():
    with _lock:
        return _clock


def set_clock(dt):
    global _clock
    with _lock:
        _clock = dt


def reset_store():
    """Reset every entity dict and the logical clock (used only in tests)."""
    global _clock
    with _lock:
        for d in _TABLES.values():
            d.clear()
        _clock = _DEFAULT_CLOCK


# Entity tables: dicts keyed by id.
_TABLES = {
    "stations": {},
    "pads": {},
    "weather_events": {},
    "fluid_tanks": {},
    "airlines": {},
    "deice_requests": {},
    "deice_operations": {},
    "inspections": {},
    "discharge_permits": {},
    "effluent_readings": {},
    "spill_reports": {},
    "recycling_contracts": {},
    "invoices": {},
}

stations = _TABLES["stations"]
pads = _TABLES["pads"]
weather_events = _TABLES["weather_events"]
fluid_tanks = _TABLES["fluid_tanks"]
airlines = _TABLES["airlines"]
deice_requests = _TABLES["deice_requests"]
deice_operations = _TABLES["deice_operations"]
inspections = _TABLES["inspections"]
discharge_permits = _TABLES["discharge_permits"]
effluent_readings = _TABLES["effluent_readings"]
spill_reports = _TABLES["spill_reports"]
recycling_contracts = _TABLES["recycling_contracts"]
invoices = _TABLES["invoices"]

LOCK = _lock
