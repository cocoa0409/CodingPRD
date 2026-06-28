"""In-memory data store (PRD §2.4, §2.5).

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every fresh process — nothing is seeded, preloaded, or hardcoded. Tests build
all state via the declared API surface. start.sh re-invocation wipes every byte
of state because a fresh Python process re-imports this module.

Common fields (PRD §2.4):
  - id: server-minted UUID with NO type prefix
  - created_at: ISO 8601 UTC, 3 fractional digits, stamped on create
  - updated_at: refreshed on every mutation (full-field entities only)
  - version: integer, starts at 1, +1 on every mutation (full-field entities only)

Append-only records (id + created_at only, no updated_at, no version):
  LotConsumption, CheckweighSample, CmrLedgerEntry, SanitationEvent.
"""
import uuid

import clock

# Each table is a dict id -> record (plain dict).
customers = {}
components = {}
component_lots = {}
recipes = {}
bom_lines = {}
production_lines = {}
crews = {}
production_runs = {}
lot_consumptions = {}
checkweigh_samples = {}
cmr_ledger_entries = {}
sanitation_events = {}

# Monotonic insertion counter to give a stable creation order independent of
# timestamp collisions (the logical clock can produce identical created_at).
_seq = 0


def reset():
    """Wipe all state. Called at process startup for total cleanliness."""
    global _seq
    customers.clear()
    components.clear()
    component_lots.clear()
    recipes.clear()
    bom_lines.clear()
    production_lines.clear()
    crews.clear()
    production_runs.clear()
    lot_consumptions.clear()
    checkweigh_samples.clear()
    cmr_ledger_entries.clear()
    sanitation_events.clear()
    _seq = 0
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def _stamp_iso():
    """created_at/updated_at use the server logical clock (PRD §2.11)."""
    return clock.to_iso_millis(clock.now())


def new_full_record(fields):
    """Create a record with the full common-field set (id, created_at,
    updated_at, version)."""
    rid = new_id()
    ts = _stamp_iso()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(fields)
    rec["_seq"] = _next_seq()
    return rec


def new_append_record(fields):
    """Create an append-only record (id, created_at only)."""
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": _stamp_iso(),
    }
    rec.update(fields)
    rec["_seq"] = _next_seq()
    return rec


def touch(rec):
    """Mutate a full-field record: refresh updated_at, bump version (PRD §2.5)."""
    rec["updated_at"] = _stamp_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


# --- Serialization: strip private fields when emitting to clients ---

def public(rec):
    """Return a JSON-safe copy of a record without internal (_-prefixed) keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
