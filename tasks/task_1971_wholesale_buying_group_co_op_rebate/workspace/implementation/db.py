"""In-memory data store. Fresh process => fresh, empty store.

Per the task contract the store MUST NOT be seeded at startup: every entity
is constructed through the declared API surface (POST /coop/bootstrap first).
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.coop = None                      # singleton dict or None
        self.members = {}                     # id -> Member
        self.suppliers = {}                   # id -> Supplier
        self.programs = {}                    # id -> SupplierProgram
        self.enrollments = {}                 # id -> ProgramEnrollment
        self.reports = {}                     # id -> PurchaseReport
        self.audits = {}                      # id -> VolumeAudit
        self.accruals = {}                    # id -> RebateAccrual
        self.distributions = {}               # id -> QuarterlyDistribution
        self.clawbacks = {}                   # id -> ClawbackCase
        self.holdbacks = {}                   # id -> HoldbackRelease
        # Logical wall clock (PRD §2.5); drives created_at / updated_at.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0                          # monotonic creation counter


store = Store()


def iso_now():
    """Render the logical clock as ISO 8601 UTC with three fractional digits."""
    dt = store.clock.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 timestamp; returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_entity():
    """Mint the four system-managed fields shared by every entity (PRD §2.4)."""
    store.seq += 1
    now = iso_now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.seq,
    }


def touch(ent):
    """Every mutation of an entity increments version and refreshes updated_at."""
    ent["version"] += 1
    ent["updated_at"] = iso_now()


def get_coop():
    from errors import err_not_found
    if store.coop is None:
        raise err_not_found("Co-op has not been bootstrapped")
    return store.coop


def public(ent):
    """Strip internal bookkeeping keys (prefixed with _) before serialization."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
