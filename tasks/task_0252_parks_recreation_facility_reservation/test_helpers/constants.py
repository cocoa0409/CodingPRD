"""Domain thresholds — numeric constants from the PRD's calculations."""

# Cancellation refund lead-time tiers (hours before start_at), PRD §3.7.
REFUND_LEAD = {
    "FULL_REFUND_LEAD_HOURS": 168,    # >= 7 days  -> full fee refund
    "PARTIAL_REFUND_LEAD_HOURS": 48,  # >= 2 days and < 7 days -> 50% fee refund
    "FORFEIT_LEAD_HOURS": 24,         # < 1 day -> deposit forfeited
}

# Patron standing thresholds on trailing no-show strikes, PRD §3.1.
STANDING = {
    "PROBATION_STRIKES": 2,  # >= 2 -> PROBATION
    "BARRED_STRIKES": 4,     # >= 4 -> BARRED
}

# Lottery selection weights, PRD §3.9.
LOTTERY_WEIGHT = {
    "WEIGHT_RESIDENT_VERIFIED": 2,
    "WEIGHT_DEFAULT": 1,
}

# Pagination bounds, PRD §2.3.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}
