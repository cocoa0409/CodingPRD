"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Standard agreement term used across tests unless overridden.
DEFAULT_TERM_START = "2026-01-01"
DEFAULT_TERM_END = "2027-12-31"

# Rate profiles per income type: (in_term_rate_bps, sunset_rate_bps, sunset_months).
DEFAULT_RATE_PROFILES = {
    "TOURING": (1500, 750, 12),
    "RECORDING": (2000, 1000, 24),
    "PUBLISHING": (2500, 1250, 24),
    "ENDORSEMENT": (1000, 500, 6),
}

THRESHOLDS = {
    # Statement disbursement threshold: net_payable >= 50000 disburses.
    "MIN_DISBURSEMENT_CENTS": 50000,
    # Expense approval routing tiers (inclusive upper bounds).
    "EXPENSE_TIER1_MAX_CENTS": 100000,
    "EXPENSE_TIER2_MAX_CENTS": 1000000,
    # Opportunity value above which artist approval is required (strict >).
    "ARTIST_APPROVAL_THRESHOLD_CENTS": 10000000,
    # Audit cost allocation: firm bears at ratio >= 5% or underpayment >= 2500000.
    "FIRM_BEARING_FLOOR_CENTS": 2500000,
    # Counter-offer movement band: <= 10% stays NEGOTIATING.
    "COUNTER_OFFER_STAY_BAND": 0.10,
    # Dispute window length in days from issuance.
    "DISPUTE_WINDOW_DAYS": 30,
    # Audit right window length in days from issuance (inclusive).
    "AUDIT_WINDOW_DAYS": 365,
    # Trailing-average window length in days ending on the clock date.
    "TRAILING_WINDOW_DAYS": 365,
    # Maximum number of times an audit may be reopened.
    "AUDIT_REOPEN_MAX": 2,
    # Default travel buffer applied on convert/exercise-born engagements.
    "DEFAULT_TRAVEL_BUFFER_HOURS": 24,
    # Default business-manager expense authority cap.
    "DEFAULT_AUTHORITY_EXPENSE_CAP_CENTS": 100000,
}
