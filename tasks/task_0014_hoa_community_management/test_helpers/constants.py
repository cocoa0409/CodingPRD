"""Domain thresholds and weights — numeric constants from the PRD.

Sources:
  - PRD §3.1: Community governance defaults.
  - PRD §3.5: Tiered fine schedule.
  - PRD §3.8: Reserve adequacy bands; CASH_FLOW horizon.
"""

# Community governance defaults (PRD §3.1).
DEFAULT_LATE_FEE_GRACE_DAYS = 15
DEFAULT_LATE_FEE_FLAT_CENTS = 2500
DEFAULT_LATE_FEE_PCT_BPS = 1000  # 10% of overdue principal per cycle
DEFAULT_LIEN_THRESHOLD_CENTS = 250000
DEFAULT_ELECTION_QUORUM_PCT = 33
DEFAULT_RESERVE_INFLATION_BPS = 300

# Tiered fine schedule (PRD §3.5).
FINE_TIER_1_CENTS = 10000
FINE_TIER_2_CENTS = 25000
FINE_TIER_3_CENTS = 50000
FINE_TIER_CAP_CENTS = 100000  # tier 4 or higher

# Rolling window for tier counting (PRD §3.5).
VIOLATION_TIER_WINDOW_DAYS = 365

# Contest deadline after opened_at (PRD §3.5).
VIOLATION_CONTEST_WINDOW_DAYS = 30

# Foreclosure cool-off after Lien.filed_at (PRD §3.4).
FORECLOSURE_COOLDOWN_DAYS = 180

# Election ballot window minimum duration (PRD §3.7).
ELECTION_WINDOW_MIN_DAYS = 14

# ACC revision cap (PRD §3.6).
ACC_REVISION_LIMIT = 3

# Reserve study horizon (PRD §3.8).
RESERVE_CASH_FLOW_HORIZON_YEARS = 30

# Reserve adequacy bands (basis points; PRD §3.8).
RESERVE_BAND_STRONG_BPS = 7000
RESERVE_BAND_FAIR_BPS = 3000
RESERVE_FULL_FUNDED_BPS = 10000  # convention when projected_obligation_cents == 0
