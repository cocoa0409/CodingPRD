"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""

import threading
import uuid

import clockutil

LOCK = threading.RLock()

COLLECTIONS = (
    "petitions",
    "classifications",
    "election_agreements",
    "voter_lists",
    "voter_list_entries",
    "supervisors",
    "campaign_communications",
    "election_rounds",
    "poll_sessions",
    "challenged_ballots",
    "objections",
    "ulp_charges",
)

DB = {name: {} for name in COLLECTIONS}


def new_id():
    return str(uuid.uuid4())


def insert(collection, row):
    """Mint id, created_at, updated_at and version, then persist."""
    stamp = clockutil.now_ts()
    row["id"] = new_id()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    DB[collection][row["id"]] = row
    return row


def touch(row):
    """Every mutation, direct or cascade-driven, bumps version and refreshes updated_at."""
    row["version"] = row["version"] + 1
    row["updated_at"] = clockutil.now_ts()
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def ordered(collection):
    """Every list endpoint is ordered by created_at ascending (insertion order breaks ties)."""
    return sorted(DB[collection].values(), key=lambda r: r["created_at"])


def public(row):
    """Serialize a row, dropping private bookkeeping keys."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


# ---------------------------------------------------------------- lookups

def petition(pid):
    return get("petitions", pid)


def classifications_of(petition_id):
    return [c for c in ordered("classifications") if c["petition_id"] == petition_id]


def agreements_of(petition_id):
    return [a for a in ordered("election_agreements") if a["petition_id"] == petition_id]


def voter_lists_of(petition_id):
    return [v for v in ordered("voter_lists") if v["petition_id"] == petition_id]


def entries_of(voter_list_id):
    return [e for e in ordered("voter_list_entries") if e["voter_list_id"] == voter_list_id]


def supervisors_of(petition_id):
    return [s for s in ordered("supervisors") if s["petition_id"] == petition_id]


def communications_of(petition_id):
    return [m for m in ordered("campaign_communications") if m["petition_id"] == petition_id]


def rounds_of(petition_id):
    return [r for r in ordered("election_rounds") if r["petition_id"] == petition_id]


def sessions_of(round_id):
    return [s for s in ordered("poll_sessions") if s["election_round_id"] == round_id]


def ballots_of_session(session_id):
    return [b for b in ordered("challenged_ballots") if b["poll_session_id"] == session_id]


def ballots_of_round(round_id):
    session_ids = set(s["id"] for s in sessions_of(round_id))
    return [b for b in ordered("challenged_ballots") if b["poll_session_id"] in session_ids]


def objections_of_round(round_id):
    return [o for o in ordered("objections") if o["election_round_id"] == round_id]


def charges_of(petition_id):
    return [c for c in ordered("ulp_charges") if c["petition_id"] == petition_id]


def current_round(petition_id):
    """The highest-numbered round on the case, or None when no round exists yet."""
    rounds = rounds_of(petition_id)
    if not rounds:
        return None
    return max(rounds, key=lambda r: r["round_number"])


def round_of_session(session):
    return get("election_rounds", session["election_round_id"])


def petition_of_session(session):
    rnd = round_of_session(session)
    return petition(rnd["petition_id"]) if rnd else None


def list_of_entry(entry):
    return get("voter_lists", entry["voter_list_id"])
