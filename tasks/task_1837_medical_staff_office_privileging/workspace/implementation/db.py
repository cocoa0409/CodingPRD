"""In-memory data store and logical clock.

The store starts completely empty on every boot. Nothing is seeded.
"""
import itertools
from datetime import datetime, timezone

# --- Logical clock ---------------------------------------------------------
# Fixed startup default; never falls back to wall-clock time.
_CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"
_clock = {
    "raw": _CLOCK_DEFAULT_RAW,
    "dt": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
}


def clock_now():
    return _clock["dt"]


def clock_raw():
    return _clock["raw"]


def set_clock(raw, dt):
    _clock["raw"] = raw
    _clock["dt"] = dt


# --- Stores -----------------------------------------------------------------
members = {}
criteria = {}
applications = {}
verification_items = {}
delineations = {}
grants = {}
reviews = {}
metrics = {}
credentials = {}
temps = {}
cases = {}
panels = {}
npdb_reports = {}
agenda_items = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)
