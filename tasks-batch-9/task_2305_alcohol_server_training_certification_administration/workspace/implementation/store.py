"""In-memory data store and the server-managed logical clock.

The store is EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every entity is created exclusively through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD 2.6 -- at startup the logical clock reads exactly this instant and
# never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = (
    "state_jurisdictions",
    "courses",
    "course_approvals",
    "trainers",
    "class_sessions",
    "alcohol_servers",
    "enrollments",
    "exam_attempts",
    "certificates",
    "registry_submissions",
    "employer_accounts",
    "employer_locations",
    "server_assignments",
    "dram_shop_documents",
    "compliance_runs",
)


class Store:
    def __init__(self):
        self.tables = {k: {} for k in KINDS}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


# --- row helpers -----------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def sort_key(row):
    """Ascending creation order; the insertion sequence breaks clock ties."""
    return (row["created_at"], row["_seq"])


def create_row(kind, fields, common_fields=True):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = store.clock
    if common_fields:
        row["updated_at"] = store.clock
        row["version"] = 1
    row["_seq"] = store.next_seq()
    row["_kind"] = kind
    store.tables[kind][row["id"]] = row
    return row


def touch(row):
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = store.clock
    return row


def apply_changes(row, changes):
    """Assign the given fields; bump version/updated_at only on a real change."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return store.tables[kind].get(row_id)


def rows(kind):
    return sorted(store.tables[kind].values(), key=sort_key)
