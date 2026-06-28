"""Domain thresholds — numeric constants from the PRD calculation narratives (§3)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Pricing / discount (§3.6)
FULL_CASE_RATE = 0.15
MIXED_CASE_RATE = 0.10
MIXED_CASE_MIN_UNITS = 12
DEFAULT_SALES_TAX_RATE = 0.0725

# Age (§3.1)
LEGAL_FLOOR_AGE = 21

# Compliance scoring (§3.2)
LIMIT_GRACE_ML = 750
WATCH_MAX_SCORE = 2

# Club tiers (§3.8)
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 200000

# Special order negotiation (§3.9)
MAX_NEGOTIATION_ROUNDS = 3

# Test clock — instances that depend on age/expiry set this so DOB 2000-01-01
# proves age 26 (>=21) and IDs expiring 2030-01-01 are valid (PRD §2.8).
TEST_CLOCK_ISO = "2026-06-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"
