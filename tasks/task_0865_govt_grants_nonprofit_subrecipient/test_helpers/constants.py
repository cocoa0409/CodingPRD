"""Domain thresholds and shared date defaults from the PRD's numeric rules."""

THRESHOLDS = {
    "MIN_PANEL_REVIEWS": 3,
    "SUBAWARD_PERIOD_GAP_DAYS": 30,
    "SINGLE_AUDIT_THRESHOLD_CENTS": 75_000_000,
    "DE_MINIMIS_INDIRECT_RATE": 0.10,
    "MTDC_SUBAWARD_CAP_CENTS": 2_500_000,
    "SIZE_COMPONENT_BUDGET_CENTS": 50_000_000,
}

# Server logical clock default (PRD §2.12).
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# Common windows reused across setups.
DEFAULT_OPEN_DATE = "2026-05-01T00:00:00Z"
DEFAULT_CLOSE_DATE = "2026-12-31T00:00:00Z"
DEFAULT_PERIOD_START = "2026-06-01T00:00:00Z"
DEFAULT_PERIOD_END = "2027-05-31T00:00:00Z"
DEFAULT_DRAWDOWN_PERIOD_START = "2026-06-01T00:00:00Z"
DEFAULT_DRAWDOWN_PERIOD_END = "2026-06-30T00:00:00Z"

# The six-line MTDC example budget (total 26,200,000 cents).
MTDC_BUDGET_LINES = [
    {"category": "PERSONNEL", "amount_cents": 10_000_000, "federal_share_pct": 1.0},
    {"category": "FRINGE", "amount_cents": 3_000_000, "federal_share_pct": 1.0},
    {"category": "TRAVEL", "amount_cents": 1_000_000, "federal_share_pct": 1.0},
    {"category": "SUPPLIES", "amount_cents": 500_000, "federal_share_pct": 1.0},
    {"category": "EQUIPMENT", "amount_cents": 4_000_000, "federal_share_pct": 1.0},
    {"category": "CONTRACTUAL", "amount_cents": 6_000_000, "federal_share_pct": 1.0},
]
MTDC_BUDGET_TOTAL_CENTS = 26_200_000

# Default single-line balanced budget under DE_MINIMIS (10,000,000 + 1,000,000 indirect).
DEFAULT_BUDGET_LINE = {"category": "PERSONNEL", "amount_cents": 10_000_000, "federal_share_pct": 1.0}
DEFAULT_TOTAL_BUDGET_CENTS = 11_000_000
