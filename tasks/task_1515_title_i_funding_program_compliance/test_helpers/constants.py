"""Domain thresholds and arithmetic helpers (PRD §2.5, §3.3-§3.10)."""

# --- Ranking thresholds (basis points; PRD §3.3) ---
MUST_SERVE_BP = 7500
ELIGIBLE_BP = 3500
SCHOOLWIDE_BP = 4000

# --- Set-aside rules (PRD §3.4) ---
PE_THRESHOLD_CENTS = 50_000_000        # $500,000.00 — strictly-greater-than
PE_RATE_PCT = 1                        # one percent of total_allocation_cents
HOMELESS_FLOOR_CENTS = 500_000         # $5,000.00 floor
HOMELESS_RATE_PER_MILLE = 5            # one-half of one percent of net
PD_RATE_PCT = 5                        # five percent of net_allocable_cents
PE_SCHOOL_DISTRIBUTION_PCT = 90        # ninety percent of reserved_cents

# --- Waterfall weights (PRD §3.4) ---
WEIGHT_MUST_SERVE = 150
WEIGHT_SCHOOLWIDE = 125
WEIGHT_TARGETED = 100
WEIGHT_ELECTED = 125

# --- Carryover (PRD §3.10) ---
CARRYOVER_LIMIT_BP = 1500              # fifteen percent ceiling

# --- Narrative / consultation minimums (PRD §3.5, §3.6, §3.9) ---
NARRATIVE_MIN_CHARS = 50
MIN_CONSULTATION_SESSIONS = 2

# --- Logical clock startup default (PRD §2.10) ---
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Waiver lookback (PRD §3.10) ---
WAIVER_LOOKBACK_YEARS = 3


def round_half_up_ratio(numerator: int, denominator: int) -> int:
    """Integer round-half-up of numerator/denominator for non-negative inputs.

    PRD §2.5: "the value is rounded half up to the nearest integer (cents or
    basis points, per the field)".
    """
    assert denominator > 0
    return (2 * numerator + denominator) // (2 * denominator)
