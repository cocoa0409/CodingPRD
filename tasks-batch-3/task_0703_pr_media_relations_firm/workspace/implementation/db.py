"""In-memory data store.

Storage is purely in-memory (Python dicts keyed by id). The store starts EMPTY
on every boot: nothing is seeded, preloaded, or hardcoded. Tests build all
preconditions through the declared API surface.

A monotonic insertion sequence is captured on each record as `_seq` so that
list endpoints can sort by creation order (PRD 2.3: created_at ascending) even
when several records share the same logical-clock-independent wall timestamp.
"""
import uuid

# One dict per entity collection: id -> record dict.
clients = {}
outlets = {}
journalists = {}
campaigns = {}
retainer_periods = {}
spokespersons = {}
media_lists = {}
pitches = {}
press_releases = {}
distributions = {}
coverage = {}
interviews = {}
crisis_events = {}
time_entries = {}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    """Server-minted UUID identifier, no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())
