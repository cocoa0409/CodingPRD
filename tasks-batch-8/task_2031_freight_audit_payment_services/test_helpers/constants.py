"""Domain thresholds and shared values from the PRD's calculation rules.

Covers: client audit-policy defaults (PRD §3.1), fuzzy duplicate detection
bounds (§3.3), discount tiers (§3.8), negotiation round limit (§3.5),
allocation total (§3.6), and the logical-clock startup default (§2.4).
"""

# PRD §2.4: before any call, the logical clock reads exactly this instant.
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_LATE = "2026-09-15T00:00:00Z"

# PRD §3.1: audit-policy defaults riding on a client account.
DEFAULT_AUDIT_TOLERANCE_MINOR = 500
DEFAULT_AUDIT_TOLERANCE_PCT_BP = 200
DEFAULT_DISPUTE_WINDOW_DAYS = 30

# PRD §3.2: default carrier payment terms.
DEFAULT_PAYMENT_TERMS_DAYS = 30

# PRD §3.3: fuzzy duplicate detection bounds (both inclusive).
FUZZY_AMOUNT_TOLERANCE_BP = 50
FUZZY_DATE_WINDOW_DAYS = 7

# PRD §3.5: at most three counters per exception.
MAX_NEGOTIATION_ROUNDS = 3

# PRD §3.6: allocation shares across a set must sum to exactly 10000 bp.
ALLOCATION_TOTAL_BP = 10000

# PRD §3.7: exchange rates are parts per million.
PPM_DENOMINATOR = 1_000_000

# PRD §3.8: early-settlement discount tiers keyed on pre-discount gross.
TIER1_THRESHOLD_MINOR = 1_000_000
TIER1_BP = 150
TIER2_THRESHOLD_MINOR = 5_000_000
TIER2_BP = 250
AUTO_FILL_DUE_WINDOW_DAYS = 7

# Shared scenario dates.
SHIP_DATE = "2026-08-02"
INVOICE_DATE = "2026-08-03"
RUN_DATE = "2026-08-10"

# Standard rated outcome for the canonical 500 kg US->CA LTL fixture
# (150/kg base, 10% fuel, LIFTGATE 5000 flat under a 20% cap, min 20000).
STANDARD_RATED_TOTAL = 87500
STANDARD_BASE_RATED = 75000
STANDARD_FUEL_RATED = 7500
STANDARD_LIFTGATE_RATED = 5000
