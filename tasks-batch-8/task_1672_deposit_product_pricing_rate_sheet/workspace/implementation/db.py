"""In-memory data store + logical clock. Starts empty on every boot."""

from datetime import datetime, timezone

STORE = {
    "products": {},
    "sheets": {},
    "scans": {},
    "cycles": {},
    "promos": {},
    "exceptions": {},
    "accounts": {},
    "curves": {},
    "bundles": {},
    "enrollments": {},
    "notices": {},
    "deployments": {},
    "migrations": {},
}

# Logical clock: server startup default is exactly 2026-08-01T00:00:00Z.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now_dt():
    return CLOCK["now"]


def today():
    return CLOCK["now"].date()
