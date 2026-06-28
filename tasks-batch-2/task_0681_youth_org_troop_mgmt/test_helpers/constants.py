"""Domain thresholds — numeric constants from the PRD calculations and gates."""

# Dues proration (PRD §3.3): full-dues floor of nine months remaining.
FULL_DUES_MONTHS = 9

# Tiered troop commission (PRD §3.7): marginal tier schedule on units.
TIER1_MAX = 100        # units 1..100 earn RATE1
TIER2_MAX = 500        # units 101..500 earn RATE2; units >500 earn RATE3
RATE1 = 0.15
RATE2 = 0.20
RATE3 = 0.25

# Recharter posture gate (PRD §2.5): pinned minimums.
MIN_YOUTH = 5
MIN_LEADERS = 2

# Default council fiscal parameters used across fixtures.
DEFAULT_CHARTER_FEE_CENTS = 30000
DEFAULT_YOUTH_DUES_CENTS = 12000
DEFAULT_ADULT_DUES_CENTS = 4500
DEFAULT_PROGRAM_YEAR = 2026

# Distinct operator identifiers for segregation-of-duties scenarios.
LEADER_USER_ID = "leader-bob"
REGISTRAR_USER_ID = "registrar-amy"
OTHER_REGISTRAR_USER_ID = "registrar-zoe"
