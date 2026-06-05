"""Domain thresholds — numeric constants from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Giving-tier boundaries (PRD Section 3.4).
GIVING_TIER = {
    "ENTRY_CEILING_CENTS": 50000,    # lifetime < 50000 -> ENTRY; == 50000 -> MID
    "MAJOR_FLOOR_CENTS": 1000000,    # lifetime >= 1000000 -> MAJOR
}

# Receipt numbering (PRD Section 3.9).
RECEIPT = {
    "PREFIX": "RCPT-",
    "PAD_WIDTH": 6,
}

# Employer matching-gift defaults (PRD Section 3.6).
EMPLOYER_DEFAULTS = {
    "MATCH_RATIO": 1.0,
    "MIN_GIFT_CENTS": 2500,
    "MAX_MATCH_CENTS": 1000000,
    "ANNUAL_MATCH_CAP_CENTS": 5000000,
}

# Pagination bounds (PRD Section 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# Donor lapse default (PRD Section 3.2).
LAPSE_THRESHOLD_DEFAULT_DAYS = 365

# A fixed campaign window used throughout setup helpers.
DEFAULT_STARTS_ON = "2026-01-01T00:00:00Z"
DEFAULT_ENDS_ON = "2026-12-31T00:00:00Z"
WIDE_STARTS_ON = "2025-12-01T00:00:00Z"


def receipt_number(seq: int) -> str:
    """Format the nth (1-based) receipt number as RCPT-000001 style."""
    return RECEIPT["PREFIX"] + str(seq).zfill(RECEIPT["PAD_WIDTH"])
