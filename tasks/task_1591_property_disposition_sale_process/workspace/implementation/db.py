"""In-memory data store. Empty on every boot; no seeding, no persistence."""

# Entity stores keyed by id (insertion-ordered dicts preserve creation order,
# which matches the created_at-ascending list contract since all timestamps
# come from the same logical clock).
assets = {}
analyses = {}
engagements = {}
packages = {}
bidders = {}
bids = {}
psas = {}
deposits = {}
dd_items = {}
payoffs = {}
statements = {}
escrows = {}

# The single server-side logical clock (ISO 8601 UTC string, 'Z' suffix).
# Startup default is exactly 2026-08-01T00:00:00Z; never falls back to wall clock.
clock_now = "2026-08-01T00:00:00Z"
