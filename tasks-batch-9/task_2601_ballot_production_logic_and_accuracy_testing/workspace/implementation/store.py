"""In-memory data store.  Starts empty on every boot -- nothing is ever seeded."""

import util

COLLECTIONS = (
    "elections",
    "contests",
    "candidates",
    "precincts",
    "ballot_styles",
    "print_vendors",
    "print_jobs",
    "ballot_lots",
    "tabulator_units",
    "test_decks",
    "la_sessions",
    "custody_events",
)

DB = {name: {} for name in COLLECTIONS}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def insert(collection, row, versioned=True):
    """Stamp the system fields and store the row."""
    stamp = util.now_str()
    row["id"] = row.get("id") or util.new_id()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    DB[collection][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = util.now_str()
    row["version"] = row.get("version", 1) + 1
    return row


def setf(row, **changes):
    """Apply field changes; bump updated_at/version once if anything moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def order_key(row):
    """Stable created_at ASC ordering (insertion sequence breaks equal stamps)."""
    return (row["created_at"], row["_seq"])


def all_rows(collection):
    return list(DB[collection].values())


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


# --- convenience child selectors --------------------------------------------

def contests_of(election_id):
    return [c for c in DB["contests"].values() if c["election_id"] == election_id]


def candidates_of(contest_id):
    return [c for c in DB["candidates"].values() if c["contest_id"] == contest_id]


def precincts_of(election_id):
    return [p for p in DB["precincts"].values() if p["election_id"] == election_id]


def styles_of(election_id):
    return [s for s in DB["ballot_styles"].values() if s["election_id"] == election_id]


def jobs_of_election(election_id):
    return [j for j in DB["print_jobs"].values() if j["election_id"] == election_id]


def jobs_of_style(style_id):
    return [j for j in DB["print_jobs"].values() if j["style_id"] == style_id]


def jobs_of_vendor(vendor_id):
    return [j for j in DB["print_jobs"].values() if j["vendor_id"] == vendor_id]


def lots_of_election(election_id):
    return [l for l in DB["ballot_lots"].values() if l["election_id"] == election_id]


def lots_of_job(job_id):
    return [l for l in DB["ballot_lots"].values() if l["print_job_id"] == job_id]


def lots_of_precinct(precinct_id):
    return [l for l in DB["ballot_lots"].values() if l["precinct_id"] == precinct_id]


def units_of_election(election_id):
    return [u for u in DB["tabulator_units"].values() if u["election_id"] == election_id]


def units_of_precinct(precinct_id):
    return [u for u in DB["tabulator_units"].values() if u["precinct_id"] == precinct_id]


def decks_of_style(style_id):
    return [d for d in DB["test_decks"].values() if d["style_id"] == style_id]


def sessions_of_unit(unit_id):
    return [s for s in DB["la_sessions"].values() if s["tabulator_id"] == unit_id]


def events_of_election(election_id):
    return [e for e in DB["custody_events"].values() if e["election_id"] == election_id]


def events_of_subject(subject_id):
    return [e for e in DB["custody_events"].values() if e["subject_id"] == subject_id]


def election_of_style(style):
    return get("elections", style["election_id"])


def election_of_deck(deck):
    style = get("ballot_styles", deck["style_id"])
    return get("elections", style["election_id"]) if style else None
