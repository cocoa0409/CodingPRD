"""Domain thresholds — numeric constants from PRD calculations."""

# Occupancy calc (PRD §3.2): max_occupancy = 2 * bedroom_count + 1
OCCUPANTS_PER_BEDROOM = 2
COMMON_AREA_ALLOWANCE = 1

# TOT tax calc (PRD §3.8)
TOT_BASE_RATE_BP = 800          # 8.00% base
TOT_SURGE_RATE_BP = 1200        # 12.00% surge
TOT_TIER_NIGHTS = 14            # first 14 nights base, remainder surge
TOT_FLAT_PER_NIGHT_CENTS = 300  # $3.00 flat lodging fee per night

# Penalty calc (PRD §3.8)
PENALTY_FLAT_CENTS = 2500       # $25 flat delinquency fee
PENALTY_DAILY_BP = 50           # 0.50% per day of unpaid balance
PENALTY_CAP_BP = 2500           # capped at 25% of unpaid balance

# Host standing (PRD §3.7)
HOST_BAR_THRESHOLD = 3          # strike_total >= 3 => BARRED

# Permit enforcement ladder (PRD §3.6)
PERMIT_SUSPEND_THRESHOLD = 2    # cumulative upheld strikes >= 2 => SUSPENDED
PERMIT_REVOKE_THRESHOLD = 4     # cumulative upheld strikes >= 4 => REVOKED

# Permit lifecycle timing (PRD §3.4 / §3.6)
PERMIT_DURATION_DAYS = 365
RENEWAL_WINDOW_DAYS = 30
FILING_DEADLINE_DAYS = 30

# Logical clock default (PRD §2.5)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


TEST_DEFAULTS = {
    "NIGHTLY_BASE_RATE_CENTS": 20000,
    "BEDROOM_COUNT": 3,
    "PERMIT_CAP": 5,
    "ATTESTED_OCCUPANCY": 5,
}
