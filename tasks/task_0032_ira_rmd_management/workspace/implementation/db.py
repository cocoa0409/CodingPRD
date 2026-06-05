"""In-memory data store for the IRA & RMD Management API.

The store starts empty on every boot — no entity is seeded at module load
or app startup. All entities are created via the declared API endpoints.
"""

import uuid
from datetime import datetime, timezone


# Per-entity ID-keyed dicts
owners = {}
accounts = {}
beneficiary_designations = {}
contributions = {}
conversions = {}
distributions = {}
rmd_schedules = {}
forms_1099r = {}
audit_events = {}


# Singleton system clock. current_utc is settable via /ira/_clock/set_current_utc.
# Default to a deterministic instant in 2026 to give tests a stable starting point
# until they explicitly set the clock themselves.
system_clock = {
    "current_utc": datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc),
    "current_tax_year": 2026,
}


def new_id() -> str:
    """Mint a server-side UUID as a plain string with no entity-type prefix."""
    return str(uuid.uuid4())


def now_utc() -> datetime:
    """Wall-clock UTC instant — used for created_at / updated_at stamping.

    Per PRD §2.10, the system clock is the explicit, settable instant that drives
    age/deadline/tax-year math. created_at / updated_at on resource rows are
    server clock stamps; we anchor them to the explicit SystemClock so that test
    runs that walk the clock forward produce reproducible audit timelines.
    """
    return system_clock["current_utc"]


def reset() -> None:
    """Used only for test harness re-init paths in interactive use; not invoked at boot."""
    owners.clear()
    accounts.clear()
    beneficiary_designations.clear()
    contributions.clear()
    conversions.clear()
    distributions.clear()
    rmd_schedules.clear()
    forms_1099r.clear()
    audit_events.clear()
    system_clock["current_utc"] = datetime(2026, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    system_clock["current_tax_year"] = 2026
