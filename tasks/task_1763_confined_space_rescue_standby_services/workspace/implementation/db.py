"""In-memory data store for the Confined Space Rescue Standby API.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot; no seeding, no preloading, no on-disk persistence.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------
# Startup default: exactly 2026-08-01T00:00:00Z. The server never falls back
# to wall-clock time; only POST /rescue-ops/_clock/set_current_utc moves it.
current_utc_iso = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Entity tables (all keyed by entity id)
# ---------------------------------------------------------------------------
personnel = {}
client_accounts = {}
confined_spaces = {}
rescue_plans = {}
entry_permits = {}
isolation_verifications = {}
roster_entries = {}
atmospheric_readings = {}
standby_assignments = {}
incidents = {}
billing_statements = {}
statement_lines = {}

# Monotonic insertion sequence used as a stable tie-breaker when several rows
# share the same logical created_at timestamp.
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]
