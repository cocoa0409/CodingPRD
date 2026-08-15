"""In-memory data store for the Custom-Exempt Locker API.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot; no seeding, no preloading, no on-disk persistence.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
# Before any set call, the clock reads exactly 2026-08-01T00:00:00Z and never
# consults the wall clock.
current_utc_iso = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity tables (all keyed by entity id)
# ---------------------------------------------------------------------------
customers = {}
capacity_days = {}
appointments = {}
animals = {}
shares = {}
cut_sheets = {}
invoices = {}
storage_records = {}
labels = {}

# Monotonic creation sequence: ties break creation order when several rows are
# minted at the same logical instant (created_at ties).
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]
