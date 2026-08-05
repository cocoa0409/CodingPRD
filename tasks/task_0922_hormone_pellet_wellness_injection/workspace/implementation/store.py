"""In-memory system of record.

Nothing here is seeded.  Every collection starts empty on every boot and is
populated exclusively through the declared API surface.
"""
import threading

import config
import util

# ------------------------------------------------------------ collections --
TABLES = (
    "Patient",
    "Provider",
    "Protocol",
    "ConsentRecord",
    "Consult",
    "LabPanel",
    "PelletLot",
    "StandingOrder",
    "Procedure",
    "PelletAllocation",
    "Membership",
    "SeriesPack",
    "InjectionVisit",
    "AdverseEvent",
    "FinancingPlan",
    "PatientNotification",
)

db = {name: {} for name in TABLES}

_state = threading.local()
_seq_lock = threading.Lock()
_seq = {"n": 0}

# The logical UTC clock.  Startup default is exactly 2026-05-01T00:00:00Z and
# it never falls back to the operating system's wall clock.
_clock = {"now": util.parse_dt(config.CLOCK_DEFAULT_ISO)}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def next_seq():
    with _seq_lock:
        _seq["n"] += 1
        return _seq["n"]


# ----------------------------------------------------- per-request context --
def begin_request():
    _state.touched = set()


def _touched():
    if not hasattr(_state, "touched"):
        _state.touched = set()
    return _state.touched


def create(table, row):
    """Insert a freshly minted row.  version starts at 1 (PRD 2.5)."""
    row.setdefault("id", util.new_id())
    row["_table"] = table
    row["_seq"] = next_seq()
    row["created_at"] = now()
    if table != "Protocol":
        row["updated_at"] = now()
        row["version"] = 1
    db[table][row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version once per request per row (PRD 2.5)."""
    if row is None or row.get("_table") == "Protocol":
        return row
    key = (row["_table"], row["id"])
    seen = _touched()
    row["updated_at"] = now()
    if key not in seen:
        seen.add(key)
        row["version"] = row.get("version", 1) + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def all_rows(table):
    """Every row of a table in creation order."""
    return sorted(db[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def where(table, **filters):
    out = []
    for row in all_rows(table):
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out
