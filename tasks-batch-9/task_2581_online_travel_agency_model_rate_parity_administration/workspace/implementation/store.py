"""In-memory data store. Starts completely empty on every boot: no seeding,
no preloaded entities, no persistence of any kind."""
import uuid

import clock

COLLECTIONS = (
    "markets",
    "suppliers",
    "model_agreements",
    "certifications",
    "rate_plans",
    "offers",
    "observations",
    "parity_cases",
    "overrides",
    "placements",
    "ranking_runs",
    "ranking_entries",
    "packages",
    "components",
    "bookings",
    "disputes",
    "scorecards",
)

db = {name: {} for name in COLLECTIONS}
_seq = {"n": 0}


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    _seq["n"] = 0
    clock.reset()


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_row(collection, fields, versioned=True):
    """Create a row. `versioned` False -> append-only evidence rows that carry
    only id and created_at (PRD §2.4)."""
    row = {"id": new_id(), "created_at": clock.now_iso_ms()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    row["_seq"] = next_seq()
    db[collection][row["id"]] = row
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by exactly 1."""
    if "version" in row:
        row["updated_at"] = clock.now_iso_ms()
        row["version"] += 1
    return row


def public(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def all_rows(collection):
    return list(db[collection].values())


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def created_key(row):
    """Stable (created_at, insertion sequence) sort key. The sequence resolves
    ties when several rows share the same logical-clock created_at."""
    return (row["created_at"], row["_seq"])
