"""In-memory data store (PRD: storage is in-memory; SCAFFOLD entity_topology flat).

Every collection is a plain dict keyed by id. The store starts EMPTY on every
boot — nothing is seeded, preloaded, or hardcoded. Tests build all preconditions
through the declared API surface.
"""
import itertools

# One dict per entity type, keyed by id.
venues = {}
lots = {}
films = {}
showtimes = {}
fm_channel_assignments = {}
season_passes = {}
reservations = {}
concession_items = {}
concession_orders = {}
private_rentals = {}
weather_events = {}
refund_records = {}

# Monotonic sequence used as a stable creation-order tiebreaker for list sorts
# (PRD §2.3: sorted by creation timestamp ascending). The sequence guarantees a
# total order even when two entities share a millisecond timestamp.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)
