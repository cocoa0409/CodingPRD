"""Domain thresholds — numeric constants from PRD calculations (§3.4, §3.5)."""

# Priority-score weights (PRD §3.4).
CRIT_WEIGHTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "CRITICAL": 8}
SEV_WEIGHTS = {"ROUTINE": 1, "MAJOR": 3, "OVERHAUL": 5}
OVERRUN_FLOOR = 1.0
OVERRUN_CEIL = 3.0
CORRECTIVE_BUMP = 10

# Skill / severity ranks for the assign skill gate (PRD §3.5).
SEV_RANK = {"ROUTINE": 1, "MAJOR": 2, "OVERHAUL": 3}
SKILL_RANK = {"JUNIOR": 1, "SENIOR": 2, "MASTER": 3}

# Failure-class reason codes that feed MTBF/MTTR (PRD §3.8).
FAILURE_CODES = ["MECHANICAL_FAILURE", "ELECTRICAL_FAILURE"]

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Convenient large budget that never constrains test setups.
BIG_BUDGET_CENTS = 100_000_000
