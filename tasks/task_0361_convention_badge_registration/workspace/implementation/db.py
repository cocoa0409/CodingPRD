"""In-memory data store.

Every collection is a plain dict keyed by entity id. The store starts empty on
every fresh boot — NO seeding, preloading, or hardcoded entities. Tests build all
state through the declared API surface.

A monotonically increasing sequence backs creation ordering so list endpoints can
sort by created_at ASC deterministically even when many rows share a millisecond.
"""

conventions = {}
ticket_types = {}
attendees = {}
orders = {}
ticket_line_items = {}
badges = {}
sessions = {}
session_reservations = {}
waitlist_entries = {}
exhibitors = {}
booths = {}
booth_bookings = {}

# Monotonic creation counter used as the deterministic tie-breaker for "created_at
# ascending" ordering (PRD §2.3) and for lottery / waitlist tie-breaks.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq
