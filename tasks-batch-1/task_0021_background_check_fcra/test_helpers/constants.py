"""Domain thresholds — numeric constants stated in PRD (§2.8, §3.1, §3.7)."""

# PRD §2.8 / §3.1 — federal floor on jurisdiction.pre_adverse_waiting_days.
FEDERAL_WAITING_DAY_FLOOR = 5

# PRD §3.7 — pinned failure weights per verification stream.
CRIMINAL_WEIGHT = 0.65
MVR_WEIGHT = 0.25
EDUCATION_WEIGHT = 0.10

# PRD §3.7 — risk threshold reported alongside the risk-score read.
RISK_THRESHOLD = 0.50

# PRD §2.3 — pagination defaults.
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0
