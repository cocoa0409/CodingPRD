"""Domain thresholds — numeric constants from the PRD's calculation rules."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Match-score weights (PRD §3.3).
MATCH_SCORE = {
    "W_FOCUS": 50,
    "W_BUDGET": 30,
    "W_HEADROOM": 20,
    "HEADROOM_FREE_PURSUITS": 2,   # headroom is full while open_pursuits < 3
    "HEADROOM_DECAY": 0.25,
}

# Invoice conversion (PRD §3.8).
MINUTES_PER_HOUR = 60

# Compliance posture thresholds (PRD §3.9).
COMPLIANCE = {
    "AT_RISK_AT": 1,    # late == 1 -> AT_RISK
    "DELINQUENT_AT": 2,  # late >= 2 -> DELINQUENT
}

# Server-startup logical clock default (PRD §2.9).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# Indirect-base categories (PRD §3.4): EQUIPMENT excluded from the indirect base.
INDIRECT_BASE_CATEGORIES = ("PERSONNEL", "TRAVEL", "OTHER")

# A syntactically-valid UUID guaranteed not to exist in a fresh DB.
MISSING_UUID = "00000000-0000-4000-8000-000000000999"
