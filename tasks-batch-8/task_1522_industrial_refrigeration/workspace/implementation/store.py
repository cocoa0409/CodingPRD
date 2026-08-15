"""In-memory data store, the logical clock, and version/updated_at accounting.

STORAGE IS PURELY IN-MEMORY AND STARTS COMPLETELY EMPTY ON EVERY BOOT.
There is no file, no SQLite, no JSON dump, no pickle, no cache directory and
no seeded/preloaded row of any kind.  Every entity a caller needs is created
through the declared endpoints.

The logical clock (PRD 2.5) boots at exactly 2026-08-01T00:00:00Z and moves
only via POST /psm/_clock/set_current_utc -- never wall-clock time.
"""
from util import new_id, parse_instant

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_COLLECTIONS = (
    "facilities",
    "systems",            # RefrigerationSystem
    "equipment",
    "psid_documents",
    "charge_adjustments",
    "inspections",
    "employees",
    "training_records",
    "drill_events",
    "incidents",
    "corrective_actions",
    "compliance_audits",
    "contractors",
    "hot_work_permits",
    "leak_events",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_instant(DEFAULT_CLOCK_UTC)
        self._touched = set()

    # -- logical clock ------------------------------------------------------
    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    # -- per-request version accounting -------------------------------------
    def begin_request(self):
        self._touched = set()

    def touch(self, row):
        """Mark a row as mutated by the current request.

        PRD 2.4: each mutated row's `version` advances by EXACTLY 1 per
        request, however many fields changed and however many times the
        request writes it (cascades included).  A freshly created row is
        pre-marked, so later writes inside the same cascade do not push it
        past version 1.
        """
        if row is None:
            return row
        key = id(row)
        if key in self._touched:
            return row
        self._touched.add(key)
        row["version"] = row.get("version", 0) + 1
        row["updated_at"] = self.clock
        return row

    def mark_fresh(self, row):
        self._touched.add(id(row))
        return row

    # -- creation -----------------------------------------------------------
    def create(self, collection, fields, common=True):
        row = dict(fields)
        row["id"] = new_id()
        row["created_at"] = self.clock
        if common:
            row["updated_at"] = self.clock
            row["version"] = 1
        getattr(self, collection)[row["id"]] = row
        self.mark_fresh(row)
        return row


db = Store()


def now():
    return db.clock


def touch(row):
    return db.touch(row)


def sorted_rows(rows):
    """List ordering (PRD 2.3): created_at ascending, ties broken by id."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))
