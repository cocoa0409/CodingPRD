"""Domain thresholds — numeric constants named in PRD prose (sections 3.2-3.8)."""

THRESHOLDS = {
    # PRD 3.8: breach when either unauthorized rate is strictly greater than 50 bps.
    "UNAUTH_THRESHOLD_BPS": 50,
    # PRD 3.8: trailing variant window length in days (half-open).
    "TRAILING_WINDOW_DAYS": 60,
    # PRD 3.2: surcharge applies when amount_cents is strictly greater than
    # $100,000.00; exactly $100,000.00 carries no surcharge.
    "LARGE_ENTRY_THRESHOLD_CENTS": 10_000_000,
    # PRD 3.3: same-day files reject entries above $1,000,000.00; exactly
    # $1,000,000.00 is eligible.
    "SAME_DAY_MAX_ENTRY_CENTS": 100_000_000,
    # PRD 3.6: NOC due six banking days after the received date.
    "NOC_DUE_BANKING_DAYS": 6,
    # PRD 3.7: reversal window is five banking days after the settled date.
    "REVERSAL_WINDOW_BANKING_DAYS": 5,
    # PRD 3.3: effective date at most two banking days ahead of today.
    "EFFECTIVE_DATE_MAX_BANKING_DAYS": 2,
}

TEST_DEFAULTS = {
    "EXPOSURE_LIMIT_CENTS": 10_000_000,
    "FEE_DISCOUNT_BPS": 0,
    "ENTRY_AMOUNT_CENTS": 100_000,
    "RECEIVER_ROUTING": "123456789",
    # Standard NEXT_DAY rate card used across setups (PRD 3.2).
    "NEXT_DAY_WINDOW": {
        "window_kind": "NEXT_DAY",
        "opens_at_utc": "00:00",
        "closes_at_utc": "23:00",
        "per_entry_fee_cents": 60,
        "file_fee_cents": 200,
        "large_entry_surcharge_cents": 100,
    },
    # Standard SAME_DAY_1 rate card (PRD 3.2).
    "SAME_DAY_1_WINDOW": {
        "window_kind": "SAME_DAY_1",
        "opens_at_utc": "09:00",
        "closes_at_utc": "12:00",
        "per_entry_fee_cents": 150,
        "file_fee_cents": 500,
        "large_entry_surcharge_cents": 400,
    },
    # Common business Monday used by file-intake scenarios.
    "BANKING_MONDAY": "2026-08-03",
}

# Startup value of the logical clock before any client call (PRD 2.4).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"
