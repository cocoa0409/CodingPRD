"""Domain thresholds — numeric constants named by the PRD (§3.1–§3.8)."""

THRESHOLDS = {
    # Danger-zone verdict (PRD §3.5)
    "DANGER_ZONE_LIMIT_MINUTES": 240,
    "COLD_HELD_DANGER_ABOVE_F": 41.0,
    "COLD_HELD_KILL_AT_PICKUP_F": 70.0,
    "HOT_HELD_DANGER_BELOW_F": 135.0,
    "HOT_HELD_KILL_AT_PICKUP_F": 100.0,
    # Cooler logistics (PRD §3.1, §3.3)
    "LBS_TO_LITERS": 0.5,
    "RETURN_ALLOWANCE_MINUTES": 90,
    "CLEANING_BUFFER_MINUTES": 45,
    "QUARANTINE_DEEP_CLEAN_MINUTES": 240,
    "RESERVATION_BLOCK_TOTAL_MINUTES": 135,  # 90 return allowance + 45 cleaning buffer
    # Driver reliability ledger (PRD §3.6, §3.7)
    "RELIABILITY_START": 100,
    "COMPLETION_BONUS": 5,
    "STRIKE_PENALTY": 50,
    "SUSPEND_THRESHOLD": 60,   # strictly below this suspends
    "REINSTATE_SCORE": 80,
    # Donor strike suspension (PRD §3.6)
    "DONOR_STRIKE_LIMIT": 3,   # inclusive: the 3rd upheld strike suspends
    # Delivery overage ceiling: ceil(estimated * 5/4) (PRD §3.4)
    "OVERAGE_NUMERATOR": 5,
    "OVERAGE_DENOMINATOR": 4,
    # Offer pickup window length band (PRD §3.2)
    "PICKUP_WINDOW_MIN_MINUTES": 30,
    "PICKUP_WINDOW_MAX_MINUTES": 240,
    # Re-offer loop termination (PRD §3.2)
    "MAX_FAILED_ATTEMPTS": 3,
}

TEST_DEFAULTS = {
    # Logical clock startup value (PRD §2.4)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Common rescue day used across scenarios
    "RESCUE_DATE": "2026-08-02",
}
