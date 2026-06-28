"""Domain thresholds — numeric constants from the PRD's pricing and SLA rules (§3)."""

# Type complexity factors for per-unit pricing (PRD §3.3).
TYPE_COMPLEXITY = {
    "CROWN": 1.00,
    "BRIDGE": 1.25,
    "DENTURE": 2.00,
    "ALIGNER": 0.30,
}

# Per-type turnaround hours; case takes the max across restorations (PRD §3.3).
TURN_HOURS = {
    "CROWN": 120,
    "BRIDGE": 168,
    "DENTURE": 240,
    "ALIGNER": 336,
}

# Invoice pricing percentages (PRD §3.3 / §3.6).
RUSH_PCT = 0.50
TAX_PCT = 0.0825
SLA_CREDIT_PCT = 0.20

# Rush turnaround floor (PRD §3.3).
RUSH_FLOOR_HOURS = 24

# Doctor volume-discount tier boundaries (PRD §3.3).
TIER_0_MAX = 4        # completed_case_count 0..4 -> 0%
TIER_1_MIN = 5        # 5..19 -> 5%
TIER_1_PCT = 0.05
TIER_2_MIN = 20       # 20+ -> 10%
TIER_2_PCT = 0.10

# Maximum revision cycles before a REVISE verdict is rejected (PRD §3.5).
MAX_REVISIONS = 3

# Default route buffer gap in minutes (PRD §3.1).
DEFAULT_BUFFER_MINUTES = 30

# Server startup logical-clock default (PRD §3.10).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

THRESHOLDS = {
    "RUSH_PCT": RUSH_PCT,
    "TAX_PCT": TAX_PCT,
    "SLA_CREDIT_PCT": SLA_CREDIT_PCT,
    "RUSH_FLOOR_HOURS": RUSH_FLOOR_HOURS,
    "MAX_REVISIONS": MAX_REVISIONS,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_MIN_LIMIT": 1,
}
