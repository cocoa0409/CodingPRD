"""Named constants the PRD pins for the inclusive-access billing domain."""

# PRD §3.5 — the opt-out deadline never lands fewer than five days after posting.
MIN_OPT_OUT_DAYS = 5

# PRD §3.8 — settlement/dispute tolerance is five dollars.
VARIANCE_TOLERANCE_CENTS = 500

# PRD §3.5 — a billed section drops to AT_RISK below this participation rate.
MIN_PARTICIPATION_RATE = 0.5000

# PRD §3.9 — the state's minimum savings percentage for a compliant report.
STATE_MIN_SAVINGS_PCT = 0.3000

# PRD §2.6 — ratios are carried to four decimal places.
RATIO_DECIMALS = 4

# PRD §3.6 — the SUBMITTED → GRANTED → RESCINDED → SUBMITTED cycle runs twice.
MAX_OPT_OUT_CYCLES = 2

# PRD §2.7 — both conserved quantities are conserved exactly.
DRIFT_TOLERANCE_CENTS = 0
DRIFT_TOLERANCE_SEATS = 0

# Cent-level equality is exact; ratios are compared with four-decimal tolerance.
RATIO_ABS_TOLERANCE = 0.00005

# A syntactically valid identifier that resolves to nothing.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# PRD §2.4 — the logical clock's default instant before any test sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
