"""In-memory data store. Starts completely empty on every boot — no seeding."""

# All stores are plain dicts keyed by resource id (UUID string).
advisors = {}
students = {}
assignments = {}
appointments = {}
dropin_tickets = {}
referrals = {}
interventions = {}
holds = {}
degree_plans = {}
notes = {}

# Logical clock state: starts at exactly 2026-08-01T00:00:00Z before any set call.
# Never falls back to wall-clock time.
_logical_clock_iso = "2026-08-01T00:00:00Z"


def get_logical_clock_iso():
    return _logical_clock_iso


def set_logical_clock_iso(iso_str):
    global _logical_clock_iso
    _logical_clock_iso = iso_str
