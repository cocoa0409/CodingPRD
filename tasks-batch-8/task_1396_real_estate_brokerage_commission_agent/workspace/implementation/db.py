"""In-memory data store.

All state lives in module-level dicts keyed by resource id. The store starts
EMPTY on every boot — no seeding, no preloading. The logical clock starts at
exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

from datetime import datetime, timezone

# Logical clock (PRD §2.4): startup default is exactly 2026-08-01T00:00:00Z.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"


def _parse_clock_start():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# --- entity stores (all empty at boot) ---
agents = {}                # id -> Agent dict
plans = {}                 # id -> CommissionPlan dict
enrollments = {}           # id -> PlanEnrollment dict
anniversary_periods = {}   # id -> AnniversaryPeriod dict
deals = {}                 # id -> Deal dict
settlements = {}           # id -> Settlement dict
legs = {}                  # id -> DisbursementLeg dict
ledger_entries = {}        # id -> LedgerEntry dict
tax_forms = {}             # id -> TaxForm1099 dict
trust_transactions = {}    # id -> TrustTransaction dict

# The logical clock (a datetime in UTC). Mutated only by the clock endpoint.
clock = {"now": _parse_clock_start()}


def now():
    """Current logical clock instant (aware datetime, UTC)."""
    return clock["now"]


def clock_date():
    """The UTC calendar date of the current clock instant."""
    return clock["now"].date()
