"""In-memory data store (PRD: in-memory only; no persistence).

Every collection is a dict keyed by the entity's UUID id. The store starts
EMPTY on every boot — no seeding. Each start.sh re-invocation (per-test-server
isolation) re-imports this module fresh, wiping all state.

A monotonic insertion counter (`_seq`) records creation order so that list
endpoints can sort by created_at ASC deterministically even when several
resources are minted within the same clock tick.
"""

trials = {}
criteria = {}
arms = {}
consent_documents = {}
irb_reviews = {}
participants = {}
screenings = {}
enrollments = {}
visits = {}
adverse_events = {}
payments = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
