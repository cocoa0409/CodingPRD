"""Domain thresholds — numeric constants from PRD §2.5, §3.3, §3.6–§3.9."""

THRESHOLDS = {
    # Statutory windows (PRD §3.2, §3.3, §3.8, §3.9)
    "REINSTATEMENT_PERIOD_DAYS": 90,
    "REINSTATEMENT_CUTOFF_BUSINESS_DAYS": 5,
    "NOTS_MIN_DAYS_BEFORE_SALE": 14,
    "FIRST_PUBLICATION_MIN_DAYS_BEFORE_SALE": 20,
    "PUBLICATION_MIN_GAP_DAYS": 7,
    "PUBLICATIONS_REQUIRED": 3,
    "MAX_POSTPONEMENTS_PER_NOTS": 3,
    "POSTPONEMENT_MAX_DAYS_PER_EVENT": 30,
    "DEED_RECORDING_DEADLINE_DAYS": 15,
    "CLAIMS_WINDOW_DAYS": 180,
    "AUCTION_DURATION_MINUTES": 60,
    # Quote fees (PRD §3.6)
    "REINSTATEMENT_FEE_CENTS": 50_000,
    "PAYOFF_FEE_CENTS": 25_000,
    "PREPAYMENT_PENALTY_PCT": 0.02,
    "DAYS_IN_YEAR": 365,
    # Trustee compensation fee (PRD §3.8)
    "FEE_PCT": 0.005,
    "FEE_FLOOR_CENTS": 75_000,
    "FEE_CAP_CENTS": 475_000,
    # Minimum next bid increment (PRD §3.8)
    "MIN_INCREMENT_CENTS": 50_000,
    "INCREMENT_PCT": 0.005,
    # Required bidder deposit (PRD §3.8)
    "DEPOSIT_FLOOR_CENTS": 1_000_000,
    "DEPOSIT_PCT": 0.01,
}

# The logical clock's startup instant (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Standard sale pipeline dates used across the composite fixtures: NOD recorded
# at the default clock, NOTS on the reinstatement-deadline day, weekly runs,
# and a Monday sale that satisfies both the 20-day and 14-day lookbacks.
PIPELINE = {
    "NOD_DATE": "2026-08-01",
    "NOTS_DATE": "2026-10-30",
    "PUB_DATES": ("2026-11-02", "2026-11-09", "2026-11-16"),
    "SALE_START": "2026-11-23T10:00:00Z",
    "SALE_DAY_CLOCK": "2026-11-23T10:30:00Z",
    "CLAIMS_FILE_DATE": "2026-12-01",
}
