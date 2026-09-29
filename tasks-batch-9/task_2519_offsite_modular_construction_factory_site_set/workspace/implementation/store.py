"""In-memory data store and the server's logical clock (PRD §2.10).

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded — every entity is created by a client through a declared endpoint.
"""

import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# PRD §2.10 — mandatory startup default; the server never falls back to wall time.
CLOCK_STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = (
    "ProgramAdmin",
    "DesignEngineer",
    "FactoryProductionManager",
    "ThirdPartyInspector",
    "TransportCoordinator",
    "SiteSuperintendent",
    "StateProgramOfficer",
    "AuthorityHavingJurisdiction",
    "WarrantyAdjudicator",
    "LenderDrawAdministrator",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.factories = {}
        self.agencies = {}
        self.projects = {}
        self.design_packages = {}
        self.modules = {}
        self.permits = {}
        self.inspections = {}
        self.shipments = {}
        self.defect_claims = {}
        self.draws = {}
        self.clock = CLOCK_STARTUP_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The single logical clock instant. Never wall-clock time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD §2.4)."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def base_row():
    """id + the three common properties every resource carries (PRD §2.4)."""
    stamp = db.clock
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """A mutation: refresh updated_at and increase version by exactly 1."""
    row["updated_at"] = db.clock
    row["version"] += 1


def sorted_rows(rows):
    """created_at ascending (PRD §2.3); insertion sequence breaks ties so the
    ordering the calculations depend on is fully deterministic."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def num(value):
    """Serialise a Decimal-backed number as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
