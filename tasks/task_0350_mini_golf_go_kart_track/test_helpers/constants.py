"""Domain thresholds — numeric constants drawn from the PRD calculations.

Generic NON_EXISTENT_UUID is provided by the framework, not redefined here.
"""

THRESHOLDS = {
    # Pricing: a group discount applies only when party_size >= GROUP_MIN_SIZE.
    "GROUP_MIN_SIZE": 4,
    # Tee-session turnover buffer in whole minutes.
    "TURNOVER_GAP_MINUTES": 10,
    # Waiver validity window and minor age cut-off.
    "WAIVER_VALID_DAYS": 365,
    "MINOR_AGE_YEARS": 18,
    # Arcade-wallet loyalty bonus.
    "LOYALTY_THRESHOLD_CENTS": 5000,
    "LOYALTY_BONUS_PCT": 0.10,
}
